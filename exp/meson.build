common_inc = include_directories('.')

# Conditional XRay flags (only for Clang)
cpp_args = []
link_args = []
if get_option('xray')
  cc = meson.get_compiler('cpp')
  if cc.get_id() == 'clang'
    cpp_args += ['-fxray-instrument', '-fxray-instruction-threshold=1']
    link_args += ['-fxray-instrument']
  else
    warning('XRay requested but not using Clang compiler. XRay flags will be ignored.')
  endif
endif

common_lib = static_library(
  'exp_common',
  sources: [
    'factorial.cpp',
  ],
  include_directories: common_inc,
  cpp_args: cpp_args,
  link_args: link_args,
)

# Top-level convenience main (optional)
if files('main.cpp').length() == 1
  exe_main = executable(
    'main',
    ['main.cpp'],
    include_directories: common_inc,
    link_with: common_lib,
    install: false,
    cpp_args: cpp_args,
    link_args: link_args,
  )
endif

subdir('targets')


