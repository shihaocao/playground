apps = [
  'hello.cpp',
  'factorial_cli.cpp',
  'factorial_file_in.cpp',
]

foreach app : apps
  name = app.split('.')[0]
  executable(
    name,
    [app],
    include_directories: include_directories('..', '.'),
    link_with: common_lib,
    install: false,
  )
endforeach


