import click
import yaml
from fspathtree import fspathtree
import os, stat, shutil
import platform
import logging
import itertools
from pathlib import Path
import subprocess
import locale

locale.setlocale(locale.LC_ALL,'')
encoding = locale.getpreferredencoding()

def get_project_root(path):
  dir = subprocess.check_output(["git","rev-parse","--show-toplevel"],cwd=path)
  dir = dir.strip().decode(encoding)
  if dir == "":
    raise Exception(f"Could not determine project root directlry for {str(path)}")

  return Path(dir).resolve()

def get_project_name(path):
  root = get_project_root(path)
  cmake_file = root/"CMakeLists.txt"
  project_name = None
  if cmake_file.exists():
    lines = list(filter(lambda l: l.find("project(") > -1, map(lambda l: l.replace(" ",""), cmake_file.read_text().split("\n")) ))
    if len(lines) > 1:
      click.echo(f"Found more than one 'project' command in {str(cmake_file)}.")
    elif len(lines) < 1:
      click.echo(f"Did not find a 'project' command in {str(cmake_file)}.")
    else:
      project_name = lines[0].replace(" ","").strip(")").strip("project").strip("(")

  if project_name is None:
    project_name = root.stem

    
  return project_name



def is_exe(path):
  '''Return true if file specified by path is an executable.'''
  if path.is_file():
    if os.access(str(path),os.X_OK):
      return True

  return False

def is_debug(path):
  '''Return true if file specified by path is an executable with debug info.'''
  if path.is_file():
    ret = subprocess.check_output(["file",str(path)])
    return ret.decode(encoding).find("with debug_info") > -1

  return False


def get_list_of_test_executables_in_path(path, patterns=None):
  if patterns is None:
    patterns = ["*Tests*", "*Tester*", "*Tests*.exe", "*Tester*.exe", "*unitTest*", "*unitTest*.exe"]


  executables = []
  for pattern in patterns:
    for file in path.rglob(pattern):
      file = file.resolve()
      if is_exe(file):
        executables.append(file)

  debugable_executables = []
  release_executables = []
  for file in executables:
    if is_debug(file):
      debugable_executables.append(file)
    else:
      release_executables.append(file)

  return {'all' : executables, 'release' : release_executables, 'debug' : debugable_executables }


def get_build_type_str(is_release):
  build_type = "Debug"
  if is_release:
    build_type = "Release"
  return build_type


def get_build_dir(path,is_release):
  build_type = get_build_type_str(is_release)
  root_dir = get_project_root(path)
  platorm_name = platform.system()
  build_dir = root_dir/f"build-{build_type.lower()}-{platorm_name.lower()}"
  return build_dir

def find_files_above(path,pattern,max_height = None):
  height = 0
  files = []
  for dir in itertools.chain([path], path.resolve().parents):
    if max_height is not None and height > max_height:
      files.reverse()
      return files
    for match in dir.glob(pattern):
      files.append(match)
    height += 1

  files.reverse()
  return files



@click.group(help="Clark's CMake, Conan, and C++ Project Tools.",context_settings=dict(ignore_unknown_options=True))
@click.option("--config","-c",default=".project.yml",help="Configuration file storing default options.")
@click.option("--local-config-only","-l",is_flag=True,help="Do not look for global configuration files in parent directories.")
@click.option("--build-dir","-b",help="Specify the build directory to use. By default, the build directory is computed.")
@click.pass_context
def main(ctx,config,local_config_only,build_dir):

  max_height = None
  if local_config_only:
    max_height = 0
  config_files = find_files_above(Path(),config,max_height)
  obj = dict()
  for file in config_files:
    click.echo(f"Reading configuration from {str(file)}.")
    with open(file) as f:
      conf = yaml.safe_load(f)
      if conf is not None:
        obj.update(conf)

  for k in obj.get('environment',{}):
    os.environ[k] = str(env[k])

  ctx.obj = fspathtree(obj)

  if build_dir:
    ctx.obj['/project/build-dir'] = build_dir
  


@main.command(help="Configure a CMake project.")
@click.option("--release/--debug","-R/-D",help="Configure for release mode or debug mode.")
@click.option("--install-prefix","-i",help="Specify the install directory.")
@click.option("--extra-cmake-configure-options",multiple=True,help="Extra options to pass to configure step.")
@click.option("--extra-conan-install-options",multiple=True,help="Extra options to pass to conan install step.")
@click.pass_context
def configure(ctx,release,install_prefix,extra_cmake_configure_options,extra_conan_install_options):

  if extra_cmake_configure_options is None or len(extra_cmake_configure_options) < 1:
    extra_cmake_configure_options = ctx.obj.get("/project/configure/extra-cmake-configure-options",[])
  if extra_conan_install_options is None or len(extra_conan_install_options) < 1:
    extra_conan_install_options = ctx.obj.get("/project/configure/extra-conan-install-options",[])

  build_type = get_build_type_str(release)

  root_dir = get_project_root(Path())
  build_dir = ctx.obj.get("/project/build-dir",None)
  if build_dir is None:
    build_dir = get_build_dir(Path(),release)
  else:
    build_dir = Path(build_dir)
  build_dir.mkdir(exist_ok=True)


  conan_file = build_dir/"conanfile.py"
  if not conan_file.exists():
    conan_file = build_dir/"conanfile.txt"
  if not conan_file.exists():
    conan_file = root_dir/"conanfile.py"
  if not conan_file.exists():
    conan_file = root_dir/"conanfile.txt"

  if conan_file.exists():
    click.echo(click.style(f"Using {str(conan_file)} to install dependencies with conan.",fg="green"))
    conan_cmd = ["conan","install",conan_file,"--build=missing"]
    conan_cmd += extra_conan_install_options
    subprocess.run(conan_cmd,cwd=build_dir)

  cmake_file = root_dir/"CMakeLists.txt"
  if cmake_file.exists():
    cmake_cmd = ["cmake",".."]
    cmake_cmd.append(f"-DCMAKE_BUILD_TYPE={build_type}")
    cmake_cmd += extra_cmake_configure_options

    if install_prefix:
      cmake_cmd.append(f"-DCMAKE_INSTALL_PREFIX={install_prefix}")

    if (build_dir/"activate.sh").exists():
      cmake_cmd = ['.','./activate.sh','&&'] + cmake_cmd

    subprocess.run(' '.join(cmake_cmd),cwd=build_dir,shell=True)
  ctx.obj['build_dir'] = build_dir

@main.command(help="Build a CMake project.")
@click.option("--release/--debug","-R/-D",help="Build release mode or debug mode.")
@click.option("--extra-cmake-build-options",multiple=True,help="Extra options to pass to build step.")
@click.option("--run-configure/--no-run-configure",multiple=True,help="Run the configure command, even if project has already been configured.")
@click.pass_context
def build(ctx,release,extra_cmake_build_options,run_configure):

  if extra_cmake_build_options is None or len(extra_cmake_build_options) < 1:
    extra_cmake_build_options = ctx.obj.get("project/build/extra-cmake-build-options",[])

  build_dir = ctx.obj.get("/project/build-dir",None)
  if build_dir is None:
    build_dir = get_build_dir(Path(),release)
  else:
    build_dir = Path(build_dir)

  if run_configure or not (build_dir/"CMakeCache.txt").exists():
    ctx.invoke(configure,release=release)

  cmake_cmd = ["cmake","--build","."]
  cmake_cmd += extra_cmake_build_options
  subprocess.run(cmake_cmd,cwd=build_dir)



@main.command(help="Test a C++ project by running unit tests.")
@click.option("--release/--debug","-R/-D",help="Test release mode or debug mode.")
@click.pass_context
def test(ctx,release):
  ctx.invoke(build,release=release)
  build_dir = ctx.obj.get("/project/build-dir",None)
  if build_dir is None:
    build_dir = get_build_dir(Path(),release)
  else:
    build_dir = Path(build_dir)

  test_executables = get_list_of_test_executables_in_path(build_dir)

  if release:
    tests_to_run = test_executables['release']
  else:
    tests_to_run = test_executables['debug']

  if len(tests_to_run) < 1:
    click.echo(f"Did not find any test executables in {str(build_dir)}.")
    return 1


  
  for file in tests_to_run:
    click.echo(f"Running {str(file)}")
    subprocess.run(file,cwd=build_dir)


@main.command(help="Install a CMake project into a specified directory.")
@click.argument("directory")
@click.pass_context
def install(ctx,directory):
  ctx.obj["/project/build-dir"] = ctx.obj.get('/project/build-dir', Path("build-install"))

  ctx.invoke(configure,release=True,install_prefix=directory)
  ctx.invoke(build,release=True,extra_cmake_build_options=['--target','install'])


@main.command(help="Debug a C++ project.")
@click.pass_context
def debug(ctx):
  ctx.invoke(build,release=False)
  build_dir = ctx.obj.get("/project/build-dir",None)
  if build_dir is None:
    build_dir = get_build_dir(Path(),release)
  else:
    build_dir = Path(build_dir)

  test_executables = get_list_of_test_executables_in_path(build_dir)
  tests_to_run = test_executables['debug']

  if len(tests_to_run) < 1:
    click.echo("Did not find any test executables.")
    return 1

  rrexec = shutil.which('rr')
  kernel_perf_event_paranoid = Path('/proc/sys/kernel/perf_event_paranoid')
  if kernel_perf_event_paranoid.exists():
    kernel_perf_event_paranoid = int(kernel_perf_event_paranoid.read_text())
  else:
    kernel_perf_event_paranoid = 10

  if kernel_perf_event_paranoid > 1:
    click.echo(click.style(f"The kernel perf_event_paranoid setting is {kernel_perf_event_paranoid}, but it must be <= 1 to run rr.",fg='red'))
    click.echo(f"You can changes this by running:")
    click.echo(f"sudo bash -c 'echo 1 > /proc/sys/kernel/perf_event_paranoid'")
    return 1
    

  
  for file in tests_to_run:
    res = subprocess.run([rrexec,'record',file],cwd=build_dir)
    print(res)
    if res.returncode:
      click.echo("There was a error running rr")



@main.command(help="Clean a CMake project.")
@click.option("--all/--build-only","-a/-b",help="Only remove build directories or clean evertyghing.")
@click.pass_context
def clean(ctx,all):

  def del_rw(func,path,_):
    '''
    Clear the readonly bit on path and try to remove it.
    '''
    os.chmod(path, stat.S_IWRITE)
    s.remove(path)

  for build_dir in Path(".").glob("build-*"):
    click.echo(f"Removing {str(build_dir)}.")
    shutil.rmtree(build_dir, onerror=del_rw)

  if not all:
    return 0

  subprocess.run(['git','clean','-f', '-d'])




@main.command(help="Display information for a project.")
@click.pass_context
def info(ctx):
  cwd = Path()
  project_name = get_project_name(cwd)
  build_dir_rel = get_build_dir(Path(),True)
  build_dir_deb = get_build_dir(Path(),False)

  click.echo(f"Project Name: {project_name}")
  click.echo(f"Build Directory (Release Mode): {build_dir_rel}")
  click.echo(f"Build Directory (Debug Mode): {build_dir_deb}")


@main.command(help="Create a new C++ project.")
@click.pass_context
def new(ctx):
  cwd = Path()


@main.command(help="Create a Conan editable package from a project.")
@click.argument("conan-package-reference")
@click.option("--conan-recipe-file", "-r", help="Conan recipe file.")
@click.pass_context
def make_conan_editable_package(ctx,conan_package_reference,conan_recipe_file):
  root_dir = get_project_root(Path())
  build_dir = get_build_dir(Path(),False)
  build_dir = build_dir.parent / (build_dir.name + "-conan_editable_package")
  install_dir = build_dir/"INSTALL"



  # look for conanfile.py
  conan_recipe_text = None
  if conan_recipe_file:
    conan_recipe_file = Path(conan_recipe_file).resolve()
    if not conan_recipe_file.exists():
      click.echo(click.style(f"Conan recipe file '{str(conan_recipe_file)}' does not exist. Conan requires a valid conanfile.py file to make a package editable.",fg='red'))
      return 1
    conan_recipe_text = conan_recipe_file.read_text()

  if conan_recipe_text is None:
    conan_recipe_file = build_dir/"conanfile.py"
    if not conan_recipe_file.exists():
      conan_recipe_file = root_dir/"conanfile.py"

    if conan_recipe_file.exists():
      conan_recipe_text = conan_recipe_file.read_text()

    try:
      conan_recipe_text = subprocess.check_output(['conan','get',conan_package_reference]).decode(encoding)
    except: pass


  if conan_recipe_text is None:
    click.echo(click.style(f"Could not find a conan recipe file. Conan requires a valid conanfile.py file to make a package editable.",fg='red'))
    return 1


  ctx.obj["/project/build-dir"] = build_dir
  ctx.invoke(install,directory=install_dir)


  Path(install_dir/'conanfile.py').write_text(conan_recipe_text)
  subprocess.run( ['conan','editable','add',install_dir,conan_package_reference] )


