from distutils.spawn import find_executable
from distutils.cmd import Command
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
from setuptools.dist import Distribution

import re
import os
import platform
import subprocess
import sys
import sysconfig
import fnmatch
import distutils.command.build

# Change these to the correct paths
c2rust_path     = os.path.realpath(os.path.join(os.getcwd(), "..", "..", ".."))
cc_wrapper_path = c2rust_path + "/cross-checks/c-checks/clang-plugin/cc_wrapper.sh"
cc_path         = c2rust_path + "/dependencies/llvm-6.0.0/build.{}/bin/clang".format(platform.uname()[1])
plugin_path     = c2rust_path + "/cross-checks/c-checks/clang-plugin/build/plugin/CrossChecks.so"
runtime_path    = c2rust_path + "/cross-checks/c-checks/clang-plugin/build/runtime/libruntime.a"
fakechecks_path = c2rust_path + "/cross-checks/libfakechecks"
clevrbuf_path   = c2rust_path + "/cross-checks/ReMon/libclevrbuf"

plugin_args = ['-Xclang', '-plugin-arg-crosschecks',
               '-Xclang', '-C../snudown_c.c2r',
               '-ffunction-sections', # Used by --icf
               ]

def c_files_in(directory):
    paths = []
    names = os.listdir(directory)
    for f in fnmatch.filter(names, '*.c'):
        paths.append(os.path.join(directory, f))
    return paths


def process_gperf_file(gperf_file, output_file):
    if not find_executable("gperf"):
        raise Exception("Couldn't find `gperf`, is it installed?")
    subprocess.check_call(["gperf", gperf_file, "--output-file=%s" % output_file])


def get_ext_filename_without_platform_suffix(filename):
    name, ext = os.path.splitext(filename)
    ext_suffix = sysconfig.get_config_var('EXT_SUFFIX')

    if ext_suffix == ext or ext_suffix is None:
        return filename

    ext_suffix = ext_suffix.replace(ext, '')
    idx = name.find(ext_suffix)

    return filename if idx == -1 else name[:idx] + ext


'''
extensions[0] -> extension for translating to rust
extensions[1] -> extension for translating and running rust xcheck
extensions[2] -> extension for running clang xcheck

extensions = [
    Extension(
        name='snudown',
        sources=['snudown.c', 'src/bufprintf.c'] + c_files_in('html/'),
        include_dirs=['src', 'html'],
        libraries=['snudownrust'],
        library_dirs=['translator-build']
    ),
    Extension(
        name='snudown',
        sources=['snudown.c', 'src/bufprintf.c'] + c_files_in('html/'),
        include_dirs=['src', 'html'],
        #libraries=['snudownrustxcheck', 'fakechecks'],
        libraries=['snudownrustxcheck', 'clevrbuf'],
        library_dirs=['translator-build', fakechecks_path, clevrbuf_path],
        extra_link_args=['-Wl,-rpath,{},-rpath,{}'.format(fakechecks_path, clevrbuf_path)],
    ),
    Extension(
        name='snudown',
        sources=['snudown.c', '../xchecks.c'] + c_files_in('src/') + c_files_in('html/'),
        include_dirs=['src', 'html'],
        library_dirs=[fakechecks_path, clevrbuf_path],
        #libraries=["fakechecks"],
        libraries=["clevrbuf"],
        extra_compile_args=plugin_args,
        extra_link_args=['-fuse-ld=gold', '-Wl,--gc-sections,--icf=safe',
                            '-Wl,-rpath,{},-rpath,{}'.format(fakechecks_path, clevrbuf_path)],
        extra_objects=[runtime_path],
    ),
]
'''

extensions = [
    Extension(
        name='snudown',
        sources=['snudown.c'] + c_files_in('src/') + c_files_in('html/'),
        include_dirs=['src', 'html']
    )
]

version = None
version_re = re.compile(r'^#define\s+SNUDOWN_VERSION\s+"([^"]+)"$')
with open('snudown.c', 'r') as f:
    for line in f:
        m = version_re.match(line)
        if m:
            version = m.group(1)
assert version


class BuildSnudown(distutils.command.build.build):
    user_options = distutils.command.build.build.user_options + [
    ('translate', None,
    'translate from c to rust'),

    ('rust-crosschecks', None,
    'translate then run rust crosschecks'),
    ('clang-crosschecks', None,
    'translate then run clang crosschecks'),

    ('use-fakechecks', None,
    'use the fakechecks library to print the cross-checks'),
    ]

    def build_extension(self):
        sources = ['snudown.c']
        sources.extend(c_files_in('html/'))
        libraries = []
        library_dirs= []
        extra_compile_args = []
        extra_link_args = []
        extra_objects=[]

        extensions.pop()
        if self.translate is not None:
            sources.append('src/bufprintf.c')
            library_dirs.append('translator-build')
            libraries.append('snudownrust')

        if self.rust_crosschecks is not None:
            sources.append('src/bufprintf.c')
            library_dirs.extend(['translator-build', fakechecks_path, clevrbuf_path])
            if self.use_fakechecks is not None:
                libraries.extend(['snudownrustxcheck', 'fakechecks'])
            else:
                libraries.extend(['snudownrustxcheck', 'clevrbuf'])
            holder = ['-Wl,-rpath,{},-rpath,{}'.format(fakechecks_path, clevrbuf_path)]
            extra_link_args.extend(holder)

        if self.clang_crosschecks is not None:
            # Set the compiler path to cc_wrapper.sh
            os.environ["CC"] = "{cc_wrapper} {cc} {plugin}".format(
                    cc_wrapper=cc_wrapper_path, cc=cc_path, plugin=plugin_path)
            sources.append('../xchecks.c')
            sources.extend(c_files_in('src/'))
            library_dirs.extend([fakechecks_path, clevrbuf_path])
            if self.use_fakechecks is not None:
                libraries.append('fakechecks')
            else:
                libraries.append('clevrbuf')
            extra_compile_args.extend(plugin_args)
            extra_link_args.extend(['-fuse-ld=gold', '-Wl,--gc-sections,--icf=safe',
                                '-Wl,-rpath,{},-rpath,{}'.format(fakechecks_path, clevrbuf_path)])
            extra_objects.append(runtime_path)

        return Extension(
            name='snudown',
            sources=sources,
            include_dirs=['src', 'html'],
            library_dirs=library_dirs,
            libraries=libraries,
            extra_compile_args=extra_compile_args,
            extra_link_args=extra_link_args,
            extra_objects=extra_objects,
        )

    def initialize_options(self, *args, **kwargs):
        self.translate = self.rust_crosschecks = self.clang_crosschecks = None
        self.use_fakechecks = None
        distutils.command.build.build.initialize_options(self, *args, **kwargs)

    def run(self, *args, **kwargs):
        if self.translate is not None:
            subprocess.check_call(["../translate.sh", "translate"])
            extensions.append(self.build_extension())

        if self.rust_crosschecks is not None:
            subprocess.check_call(["../translate.sh", "rustcheck"])
            extensions.append(self.build_extension())

        if self.clang_crosschecks is not None:
            subprocess.check_call(["../translate.sh"])
            extensions.append(self.build_extension())

        distutils.command.build.build.run(self, *args, **kwargs)

class GPerfingBuildExt(build_ext):
    def get_ext_filename(self, ext_name):
       filename = build_ext(Distribution()).get_ext_filename(ext_name)
       return get_ext_filename_without_platform_suffix(filename)

    def run(self):
        #translate.py builds this manually
        #process_gperf_file("src/html_entities.gperf", "src/html_entities.h")
        build_ext.run(self)

setup(
    name='snudown',
    version=version,
    author='Vicent Marti',
    author_email='vicent@github.com',
    license='MIT',
    test_suite="test_snudown.test_snudown",
    cmdclass={'build': BuildSnudown, 'build_ext': GPerfingBuildExt},
    ext_modules=extensions,
)
