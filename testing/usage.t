  $ virtualenv cccpt-install > /dev/null
  $ . cccpt-install/bin/activate
  $ cd ${TESTDIR}/..
  $ pip install . > /dev/null
  $ cd - > /dev/null
  $ which ccc
  .*/cccpt-install/bin/ccc (re)
  $ ccc --help | head -n 1
  Usage: ccc [OPTIONS] COMMAND [ARGS]...
  $ cp ${TESTDIR}/MyProject ./ -r
  $ cd MyProject
  $ ls
  CMakeLists.txt
  main.cpp
  $ ccc build  > /dev/null
  $ ls build-debug-linux/m*
  build-debug-linux/main
