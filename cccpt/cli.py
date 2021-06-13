import click
import yaml
from fspathtree import fspathtree
import pyparsing as pp

import os
import sys
import stat
import fnmatch
import shutil
import platform
import logging
import itertools
from pathlib import Path
import subprocess
import locale
import importlib.util
import inspect
import urllib.parse
import tempfile
import re
import configparser
import json
import pprint
import time
import hashlib
import shlex

locale.setlocale(locale.LC_ALL,'')
encoding = locale.getpreferredencoding()



def error(msg):
  click.echo(click.style(msg,fg='red'))

def sucess(msg):
  click.echo(click.style(msg,fg='green'))

def info(msg):
  click.echo(msg)








@click.group(context_settings=dict(ignore_unknown_options=True))
@click.option("--config","-c",type=click.Path(dir_okay=False),default=".project.yml",help="Configuration file storing default options.")
@click.option("--local-config-only","-l",is_flag=True,help="Do not look for global configuration files in parent directories.")
@click.option("--root-dir",type=click.Path(file_okay=False,exists=True,resolve_path=True),help="Specify the project root directory to use. By default, the root directory is determined from the git root directory.")
@click.option("--build-dir",type=click.Path(resolve_path=True),help="Specify the build directory to use. By default, the build directory is computed.")
@click.option("--cmake-dir",type=click.Path(file_okay=False,exists=True,resolve_path=True),help="Specify the directory containing the CMakeLists.txt file to use. By default, the project root is used.")
@click.option("--conan-dir",type=click.Path(file_okay=False,exists=True,resolve_path=True),help="Specify the directory containing the conanfile.txt or conanfile.py file to use. By default, the project root is used.")
@click.option("--verbose","-v",is_flag=True,help="Print verbose messages.")
@click.pass_context
def main(ctx,config,local_config_only,root_dir,build_dir,cmake_dir,conan_dir,verbose):
  '''
  Clark's Conan, CMake, and C++ Project Tools.
  '''

  max_height = None
  if local_config_only:
    max_height = 0
  config = Path(config)
  config_files = find_files_above(Path(),config.name,max_height)
  obj = dict()
  for file in config_files:
    if verbose:
      info(f"Reading configuration from {str(file)}.")
    conf = yaml.safe_load(file.read_text())
    if conf is not None:
      merge(obj,conf)

  for k in obj.get('environment',{}):
    os.environ[k] = str(env[k])

  ctx.obj = fspathtree(obj)
  if verbose:
    ctx.obj['/app/verbose'] = True
  else:
    ctx.obj['/app/verbose'] = False


  if build_dir:
    ctx.obj['/project/build-dir'] = Path(build_dir).resolve()
  if cmake_dir:
    ctx.obj['/project/cmake-dir'] = Path(cmake_dir).resolve()
  if conan_dir:
    ctx.obj['/project/conan-dir'] = Path(conan_dir).resolve()

  if root_dir:
    ctx.obj['/project/root-dir'] = Path(root_dir).resolve()
  else:
    try:
      ctx.obj['/project/root-dir'] = get_project_root(Path())
    except:
      ctx.obj['/project/root-dir'] = Path().resolve()

  ctx.obj['/project/config_files'] = config_files


  for cmd in ['cmake','conan','git', 'vim']:
    if '/project/commands/'+cmd not in ctx.obj:
      ctx.obj['/project/commands/'+cmd] = shutil.which(cmd)

  


@main.command()
@click.option("--release/--debug","-R/-D",help="Configure for release mode or debug mode.")
@click.option("--install-prefix","-i",help="Specify the install directory.")
@click.option("--extra-cmake-configure-options",multiple=True,help="Extra options to pass to configure step.")
@click.option("--extra-conan-install-options",multiple=True,help="Extra options to pass to conan install step.")
@click.option("--generator",help="Specify the generator to use.")
@click.pass_context
def configure(ctx,release,install_prefix,extra_cmake_configure_options,extra_conan_install_options,generator):
  '''
  Configure a CMake project.
  '''

  if extra_cmake_configure_options is None or len(extra_cmake_configure_options) < 1:
    extra_cmake_configure_options = ctx.obj.get("/project/configure/extra-cmake-configure-options",[])
  if extra_conan_install_options is None or len(extra_conan_install_options) < 1:
    extra_conan_install_options = ctx.obj.get("/project/configure/extra-conan-install-options",[])

  build_type = get_build_type_str(release)

  root_dir = ctx.obj['/project/root-dir']
  build_dir = ctx.obj.get("/project/build-dir",get_build_dir(Path(),release,root_dir))
  cmake_dir = ctx.obj.get("/project/cmake-dir",root_dir)
  conan_dir = ctx.obj.get("/project/conan-dir",root_dir)


  build_dir.mkdir(parents=True,exist_ok=True)

  conan_file = build_dir/"conanfile.py"
  if not conan_file.exists():
    conan_file = build_dir/"conanfile.txt"
  if not conan_file.exists():
    conan_file = conan_dir/"conanfile.py"
  if not conan_file.exists():
    conan_file = conan_dir/"conanfile.txt"
  print("Found conanfile:",conan_file)

  if conan_file.exists():
    sucess(f"Using {str(conan_file)} to install dependencies with conan.")
    conan  = ctx.obj.get('/project/commands/conan','conan')
    conan_cmd = [conan,"install",str(conan_file),"--build=missing","-s",f"build_type={build_type}"]
    conan_cmd += extra_conan_install_options
    info(f"Running: {conan_cmd}")
    result = subprocess.run(conan_cmd,cwd=build_dir)
    if result.returncode != 0:
      return result.returncode

  cmake_file = cmake_dir/"CMakeLists.txt"
  if cmake_file.exists():
    cmake = ctx.obj.get('/project/commands/cmake','cmake')
    cmake_cmd = [cmake,str(cmake_file.parent)]
    cmake_cmd.append(f"-DCMAKE_BUILD_TYPE={build_type}")

    # figure out if we need to specify the CMAKE_GENERATOR_PLATFORM option.
    # it is only used by the Visual Studio generators.
    if not generator:
      if "CMAKE_GENERATOR" in os.environ:
        generator = os.environ["CMAKE_GENERATOR"]
      else:
        generators = filter( lambda l : l.find(b"Generates") > 0, map(lambda l: l.strip(), subprocess.check_output([cmake,'--help']).split(b"\n")))
        default_generators = list(filter( lambda l : l.startswith(b'*'), generators))
        if len(default_generators) == 1:
          generator = re.sub(b"\s*=\s*.*$",b"",re.sub(br"^\*\s*",b"",default_generators[0]))
          generator = generator.decode(encoding)

    if generator:
      cmake_cmd.append(f"-G")
      cmake_cmd.append(generator)

    if ctx.obj['/app/verbose']:
      info(f"Using Generator: {generator}")

    if generator and generator.startswith("Visual Studio"):
      if platform.architecture()[0] == '64bit':
        cmake_cmd.append(f"-DCMAKE_GENERATOR_PLATFORM=x64")

    cmake_cmd += extra_cmake_configure_options

    if install_prefix:
      cmake_cmd.append(f"-DCMAKE_INSTALL_PREFIX={install_prefix}")

    # If a conan build info file exists, read it and load the environment variables.
    load_conan_buildinfo(build_dir)
    load_conan_environment(build_dir)

    info(f"Running: {cmake_cmd}")
    result = subprocess.run(cmake_cmd,cwd=build_dir)
    return result.returncode

  return 0

@main.command()
@click.option("--release/--debug","-R/-D",help="Build release mode or debug mode.")
@click.option("--extra-cmake-build-options",multiple=True,help="Extra options to pass to build step.")
@click.option("--target","-t",help="Build specific target.")
@click.option("--run-configure/--no-run-configure","-c/-n",multiple=True,help="Run the configure command, even if project has already been configured.")
@click.option("--parallel","-j",default=-1,help="Run the build command in with INTEGER parallel jobs if possible.")
@click.pass_context
def build(ctx,release,extra_cmake_build_options,run_configure,target,parallel):
  '''
  Build a CMake project.
  '''

  if extra_cmake_build_options is None or len(extra_cmake_build_options) < 1:
    extra_cmake_build_options = ctx.obj.get("project/build/extra-cmake-build-options",[])

  root_dir = ctx.obj['/project/root-dir']
  build_dir = ctx.obj.get("/project/build-dir",get_build_dir(Path(),release,root_dir))

  build_type = get_build_type_str(release)

  if run_configure or not (build_dir/"CMakeCache.txt").exists():
    ctx.invoke(configure,release=release)
  else:
    load_conan_buildinfo(build_dir)
    load_conan_environment(build_dir)

  if parallel < 0 or parallel > os.cpu_count():
    parallel = os.cpu_count()

  cmake = ctx.obj.get('/project/commands/cmake','cmake')
  cmake_cmd = [cmake,"--build",".","--config",build_type]
  if parallel > 0:
    cmake_cmd += ['--parallel',str(parallel)]

  if target:
    cmake_cmd += ['--target',target]
  cmake_cmd += extra_cmake_build_options
  result = subprocess.run(cmake_cmd,cwd=build_dir)
  return result.returncode



@main.command()
@click.option("--release/--debug","-R/-D",help="Test release mode or debug mode.")
@click.option("--match","-k",help="Only run test executable matching TEXT.")
@click.option("--args","-a",help="Pass arguments to test executables(s).")
@click.option("--skip-build/--run-build","-s/-b",help="Skip build phase.")
@click.option("--debugger",default="",help="Run test executables with a specified debugger.")
@click.pass_context
def test(ctx,release,match,args,skip_build,debugger):
  '''
  Test a Clark project by running unit tests.
  '''
  if not skip_build:
    ret = ctx.invoke(build,release=release)
    if ret != 0:
      error(f"Build phase returned non-zero, indicating that there was an error. Skipping test phase.")
      return ret
  

  root_dir = ctx.obj['/project/root-dir']
  build_dir = ctx.obj.get("/project/build-dir",get_build_dir(Path(),release,root_dir))

  test_executables = get_list_of_test_executables_in_path(build_dir)
  tests_to_run = test_executables['all']

  if len(tests_to_run) < 1:
    info(f"Did not find any test executables in {str(build_dir)}.")
    return 1

  # filter out duplicates
  tests_to_run = {hashlib.md5(f.read_bytes()).digest():f for f in tests_to_run}.values()

  load_conan_environment(build_dir)
  
  ret = 0
  for file in tests_to_run:
    if not match or str(file).find(match) > -1:
      info(f"Running {str(file)}")
      cmd = shlex.split(debugger)
      cmd += [str(file)]
      if args:
        cmd += shlex.split(args)
      result = subprocess.run(cmd,cwd=build_dir)
      ret += abs(result.returncode)

  return ret


@main.command(help="Install a CMake project into a specified directory.")
@click.argument("directory")
@click.option("--tag","-t", help="Checkout tag TEXT before installing. This requires `git`, and will make a copy of the repository.")
@click.pass_context
def install(ctx,directory,tag):
  ctx.obj["/project/build-dir"] = ctx.obj.get('/project/build-dir', Path("build-install"))

  directory = Path(directory).resolve()

  if not tag:
    ret = 0
    ret += ctx.invoke(configure,release=True,install_prefix=directory)
    ret += ctx.invoke(build,release=True,extra_cmake_build_options=['--target','install'])
    return ret


  with tempfile.TemporaryDirectory(suffix=".d",prefix='ccc-install') as tdir:
    odir = os.getcwd()
    root = get_project_root(Path())
    tdir = Path(tdir)
    git = ctx.obj.get('/project/commands/git','git')
    info(f"Cloning repo to '{str(tdir)}' to checkout tag '{tag}'.")
    git_cmd = ['git','clone',str(root),str(tdir)]
    res = subprocess.run(git_cmd)
    if res.returncode != 0:
      error(f"There was an error cloning repo to '{str(tdir)}'. Exiting.")
      return 1
    os.chdir(tdir)
    git_cmd = ['git','checkout',tag]
    res = subprocess.run(git_cmd)
    if res.returncode != 0:
      error(f"There was an error checking out '{tag}'. Does the tag exists? Exiting.")
      os.chdir(odir)
      return 1

    ctx.invoke(configure,release=True,install_prefix=directory)
    ctx.invoke(build,release=True,extra_cmake_build_options=['--target','install'])

    os.chdir(odir)


@main.command(help="Debug a Clark project unit tests.")
@click.option("--match","-k",help="Only run test executable matching TEXT.")
@click.pass_context
def debug(ctx,match):
  root_dir = ctx.obj['/project/root-dir']
  build_dir = ctx.obj.get("/project/build-dir",get_build_dir(Path(),False,root_dir))

  ctx.obj["/project/build-dir"] = build_dir
  ret = ctx.invoke(build,release=False)
  if ret != 0:
    error(f"Build phase returned non-zero, indicating that there was an error. Skipping test phase.")
    return ret

  test_executables = get_list_of_test_executables_in_path(build_dir)
  tests_to_run = test_executables['debug']

  if len(tests_to_run) < 1:
    info("Did not find any test executables.")
    return 1

  rrexec = shutil.which('rr')
  kernel_perf_event_paranoid = Path('/proc/sys/kernel/perf_event_paranoid')
  if kernel_perf_event_paranoid.exists():
    kernel_perf_event_paranoid = int(kernel_perf_event_paranoid.read_text())
  else:
    kernel_perf_event_paranoid = 10

  if kernel_perf_event_paranoid > 1:
    error(f"The kernel perf_event_paranoid setting is {kernel_perf_event_paranoid}, but it must be <= 1 to run rr.")
    warn(f"You can changes this by running:")
    warn(f"sudo bash -c 'echo 1 > /proc/sys/kernel/perf_event_paranoid'")
    return 1
    

  
  ret = 0
  for file in tests_to_run:
    if not match or str(file).find(match) > -1:
      info(f"Running {file} with rr.")
      res = subprocess.run([rrexec,'record',file],cwd=build_dir)
      if res.returncode:
        ret += 1
        error("There was a error running rr")

  if ret == 0:
    sucess("All test executables were ran with `rr`. You can now debug with your tool of choice (for example `gdbgui --rr`)")
    sucess("You can see a list of currently stored traces with `rr ls`.")

  return ret



@main.command(help="Clean a CMake project.")
@click.option("--all/--build-only","-a/-b",help="Only remove build directories or clean evertyghing.")
@click.pass_context
def clean(ctx,all):

  try:
    root_dir = get_project_root(Path())
  except Exception as e:
    error("The clean command can only be ran from within a project directory. Could not determine project root!")
    error(str(e))
    return 1

  for build_dir in Path(".").glob("build-*"):
    info(f"Removing {str(build_dir)}.")
    try:
      rmtree(build_dir)
    except:
      error(f"Could not remove {str(build_dir)}. You may be trying to delete files created by a different OS.")

  if not all:
    return 0

  git = ctx.obj.get('/project/commands/git','git')
  subprocess.run([git,'clean','-f', '-d'])




@main.command(help="Display information for a project.")
@click.pass_context
def info(ctx):
  cwd = Path()
  try:
    root = get_project_root(Path())
  except:
    error("The info command can only be ran from within a project directory. Could not determine project root.")
    return 1
  project_name = get_project_name(cwd)
  build_dir_rel = get_build_dir(Path(),True)
  build_dir_deb = get_build_dir(Path(),False)

  info(f"Project Name: {project_name}")
  info(f"Root Directory: {root}")
  info(f"Build Directory: (Release Mode): {build_dir_rel}")
  info(f"Build Directory: (Debug Mode): {build_dir_deb}")

  cmakelists = root.glob("**/CMakeLists.txt")
  info(f"Dependencies referenced by CMake")
  for file in cmakelists:
    info(f"{str(file.relative_to(root))}")
    text = file.read_text()
    for match in re.findall("find_package\s*\(\s*([^\s]+)",text):
      info(f"  {match}")
  
  info("Configuration:")
  pprint.pprint(ctx.obj.tree)
    

  



@main.command(help="Create a new **very basic** C++ project (here be dragons).")
@click.argument("name")
@click.pass_context
def new(ctx, name):
  '''
  Create a **very basic** empty C++ project, named NAME, based on common practices.
  This is only intended for user new to C++.
  Most users will probably find this insufficient or simply dissagree with every choice that has been made.
  New users to C++ can use it to get started quickly.

  The generated project will be based on the following tools:
    - git: for version control.
    - CMake: for build configuration.
    - Conan: for dependency managment.
    - Catch2: for unit testing.
    - Doxygen: for documentation.
    - clang-format: for code formatting.
  '''
  cwd = Path('.')
  error("This command will generate a **very basic** CMake-based C++ project..")
  error("If you have *any* experience building C++ projects,")
  error("you will almost certainly **not** like the choices made.")
  error("")
  error("It is intended for new users to get started writting C++ code")
  error("while still following best practices for the most commonly used tools.")
  error("")
  error("It currently sets up a project based on the Pitchfork Layout proposal,")
  error("https://api.csswg.org/bikeshed/?force=1&url=https://raw.githubusercontent.com/vector-of-bool/pitchfork/develop/data/spec.bs#intro.files")
  error("and is not very configurable yet.")
  error("")
  error("If you have preferences on how a project should be layed out, configured, etc,")
  error("then you should generate a new project by hand, or however you normally do it.")
  error("")
  error("As long as you use CMake and Conan in the usual way, the other commands (configure, build, etc.) will work.")
  error("")
  error("In the future, we may provide a customization point that normal users could use")
  error("to build a project based on their own preferences.")
  error("")
  error("Stay tuned...")
  error("")
  error("")


  try:
    builder = PFLBuilder(name,dir=cwd)
    builder.setup()
  except Exception as e:
    error("")
    error("There was a problem creating the new project")
    error(str(e))









@main.command()
@click.argument("conan-package-reference")
@click.option("--conan-recipe-file", "-r", help="Conan recipe file.")
@click.option("--install-prefix", "-i", help="Specify the install directory.")
@click.option("--release", "-i", help="use a release build..")
@click.pass_context
def make_conan_editable_package(ctx,conan_package_reference,conan_recipe_file,install_prefix,release):
  '''
  Create a Conan editable package from a project.

  Conan editable packages is a feature that lets you point a conan package to a
  local directory. This is useful for working on a library that other libraries
  depend on, you can test changes without modifying the client libraries conan
  recipe.

  To create an editable package, you need to install the library into a local directory
  and also provide a conanfile.py. You then run

  > conan editable add path/to/install/dir CONAN_PACKAGE_REFERENCE

  This command will first build and install the package into a local directory
  (by default this is named <build_dir>-conan_editable_package/INSTALL),
  copy the recipe file specified with --conan-recipe-file option to this directory,
  and then run conan.

  To work on a library, run this command once. Then run

  > ccc install path/to/install/dir

  to build the library. Rebuilding any clients that used the conan package will
  immediately see the changes.

  To return the package to normal, run

  > conan editable remove CONAN_PACKAGE_REFERENCE
  '''
  root_dir = ctx.obj['/project/root-dir']
  build_dir = get_build_dir(Path(),release)
  build_dir = build_dir.parent / (build_dir.name + "-conan_editable_package")
  install_dir = build_dir/"INSTALL"
  if install_prefix:
    install_dir = Path(install_prefix)

  conan = ctx.obj.get('/project/commands/conan','conan')


  # look for conanfile.py
  conan_recipe_text = None
  if conan_recipe_file:
    conan_recipe_file = Path(conan_recipe_file).resolve()
    if not conan_recipe_file.exists():
      error(f"Conan recipe file '{str(conan_recipe_file)}' does not exist. Conan requires a valid conanfile.py file to make a package editable.")
      return 1
    conan_recipe_text = conan_recipe_file.read_text()

  if conan_recipe_text is None:
    conan_recipe_file = build_dir/"conanfile.py"
    if not conan_recipe_file.exists():
      conan_recipe_file = root_dir/"conanfile.py"

    if conan_recipe_file.exists():
      conan_recipe_text = conan_recipe_file.read_text()

    try:
      conan_recipe_text = subprocess.check_output([conan,'get',conan_package_reference]).decode(encoding)
    except: pass


  if conan_recipe_text is None:
    error(f"Could not find a conan recipe file. Conan requires a valid conanfile.py file to make a package editable.")
    return 1


  ctx.obj["/project/build-dir"] = build_dir
  ctx.invoke(install,directory=install_dir,release=release)


  Path(install_dir/'conanfile.py').write_text(conan_recipe_text)
  subprocess.run( [conan,'editable','add',install_dir,conan_package_reference] )

@main.command(help="Print all source files in a project (suitable for feeding to `entr`).")
@click.option("--pattern","-p",multiple=True,help="Pattern used to identify a source file (can be given multiple times).")
@click.option("--ignore-pattern","-i",multiple=True,help="Pattern used to ignore files that have been identified as source (can be given multiple times).")
@click.option("--include-pattern","-I",multiple=True,help="Pattern used to include files that have been identified as source but match an ignore pattern (can be given multiple times).")
@click.pass_context
def list_sources(ctx,pattern,ignore_pattern,include_pattern):

  root = get_project_root(Path())
  source_patterns = ['*.cpp','*.h','*.hpp','*.py']
  source_ignore_patterns = [ '*/.git/*',str(root)+'/build*' ]
  source_include_patterns = []

  if pattern:
    source_patterns = list(pattern)
  if ignore_pattern:
    source_ignore_patterns = list(ignore_pattern)
  if include_pattern:
    source_include_patterns = list(include_pattern)


  for file in root.glob('**/*'):
    if not any(map( lambda pattern: fnmatch.fnmatch(file,pattern), source_patterns )):
      continue

    if any(map( lambda pattern: fnmatch.fnmatch(file,pattern), source_ignore_patterns )) and not any(map( lambda pattern: fnmatch.fnmatch(file,pattern), source_include_patterns )):
      continue

    click.echo(file)


@main.command(help="Extract a basic Conan file from a Conan package recipe.")
@click.argument("conan-package-recipe")
@click.option("--output-file","-o",help="Write output to file.")
@click.pass_context
def extract_basic_conan_file(ctx,conan_package_recipe,output_file):
  def get_conan_package_class(module):
    for item in dir(module):
      obj = getattr(module,item)
      if inspect.isclass(obj):
        for base in obj.__bases__:
          if base.__name__ == "ConanFile":
            return obj



  spec = importlib.util.spec_from_file_location("conanfile", conan_package_recipe)
  conanfile = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(conanfile)

  ConanPackage = get_conan_package_class(conanfile)

  lines = []
  for section in ["requires","generators"]:
    if section in ConanPackage.__dict__:
      items = ConanPackage.__dict__[section]
      if isinstance(items,str): items = [items]
      lines.append(f"[{section}]")
      lines += items
      lines.append("")


  if output_file:
    Path(output_file).write_text("\n".join(lines))
  else:
    print("\n".join(lines))

@main.command(help="Install a set of Conan package recipes.")
@click.argument("url",nargs=-1,default=None)
@click.option("--home", help="The conan user home directory to install recipes into.")
@click.pass_context
def install_conan_recipes(ctx,url,home):
  '''URL is a git repository containing Conan package recipes.
  '''
  if len(url) < 1:
    url = [click.prompt(click.style("Where are the recipes? ",fg='green'),type=str)]


  if home:
    os.environ['CONAN_USER_HOME'] = home

  conan = ctx.obj.get('/project/commands/conan','conan')
  git = ctx.obj.get('/project/commands/git','git')
  ret = 0
  for u in url:
    tdir = Path(tempfile.mkdtemp())
    res = subprocess.run([git,'clone',u,str(tdir)])
    if res.returncode != 0:
        click.echo(click.style(f'There was a problem cloning repo {u}.',fg='red'))
        ret += 1
        continue

    if (tdir/'export-packages.py').exists():
      click.echo(f"Found an export-packages.py for {u}")
      res = subprocess.run(['python','export-packages.py'],cwd=tdir)
      if res.returncode != 0:
        click.echo(click.style(f'There was a problem installing recipes in {u} with the export-packages.py script.',fg='red'))
        ret += 1
      continue

    user_channel = click.prompt(click.style(f"What user/channel should the recipes in {u} be installed under? ",fg='green'),type=str)
    exported = False

    for file in tdir.glob('**/conanfile.py'):
      exported = True
      res = subprocess.run([conan,'export',str(file),user_channel])
      if res.returncode != 0:
        click.echo(click.style(f'There was a problem manually exporting the recipes in {u}.',fg='red'))
        ret += 1
      continue

    if not exported:
      click.echo(click.style(f"Could not figure out how to export the recipes in {u}.",fg='red'))
      ret += 1

    try:
      shutil.rmtree(tdir)
    except: pass

  return ret


@main.command()
@click.argument("name")
@click.option("--remote", "-r", multiple=True,help="Specify the remote to look for project named NAME.")
@click.option("--print-errors/--no-print-errors", "-e/-n", help="Print output from failed commands.")
@click.pass_context
def get(ctx,name,remote,print_errors):
  """
  Get a copy of a project.

  This command will attempt to clone or copy a project given by NAME from all remotes listed in the configuration
  file. For example, given the configuration file

  project:
    remotes:
      - "git@github.com:CD3"
      - "git@github.com:"
      - "git@gitlab.com:"
      - "/home/me/projects"

  > ccc get SuperProject

  will look try to clone the project using

  git@github.com:CD3/SuperProject
  git@github.com:/SuperProject
  git@gitlab.com:/SuperProject
  /home/me/projects/SuperProject

  It will also try to do a simple copy of /home/me/projects/SuperProject if it exists and failed to clone.
  """
  if not remote and not '/project/remotes' in ctx.obj:
    error(f"Did not find any remotes to look for {name} project in.")
    error(f"You need to either specify a remote to use with --remote url,")
    error(f"or add a section named /project/remotes that contains a list of remote urls,")
    error(f"to one of the project configuration files.")
    return 1
  
  if len(remote) < 1:
    remote = ctx.obj['/project/remotes']

  git = ctx.obj.get('/project/commands/git','git')

  failed_remotes = []
  success_remote = None
  error_messages = []
  for r in remote:
    parsed_url = urllib.parse.urlparse(r)
    if parsed_url.scheme in ['','file']:
        src = (Path(parsed_url.path)/name)
        dest = (Path('.')/name)
        if src == dest:
          error("Cannot clone/copy project into itself.")
          return 1
        if dest.exists():
          error("Project directory already exists. Remove it or change to a different directory.")
          return 1
        try:
          cmd = [git,'ls-remote',str(Path(parsed_url.path)/name)]
          output = subprocess.check_output(cmd,stderr=subprocess.STDOUT)
          cmd = [git,'clone',str(Path(parsed_url.path)/name),name]
          output = subprocess.check_output(cmd,stderr=subprocess.STDOUT)
          success_remote = ('clone',src)
          break
        except Exception as e:
          error_messages.append(str(e))
          error_messages.append(e.output)
          if src.is_dir():
            try:
              shutil.copytree(src,dest)
              success_remote = ('copy',src)
              break
            except Exception as e:
              error_messages.append(str(e))
              failed_remotes.append(src)
          else:
            failed_remotes.append(src)
    else:
      click.echo(click.style(f"Unknown scheme {parsed_url.scheme} in URL.",fg="red"))
      failed_remotes.append(r)
      continue

  if success_remote is not None:
    click.echo(click.style(f"Sucess: {success_remote[0]}ed project from {success_remote[1]}.",fg='green'))
  else:
    click.echo(click.style(f"Fail: could not retrieve {name} from any remotes.",fg='red'))
    click.echo(click.style(f"  Tried the following:",fg='red'))
    for f in failed_remotes:
      error(f"    - {f}")
    if print_errors:
      for output in error_messages:
        info(output)
    else:
      error("To see error output, use the --print-errors option.")

@main.command()
@click.argument("name")
@click.option("--remote", "-r", multiple=True,help="Specify the remote to look for project named NAME.")
@click.option("--tags", "-t",is_flag=True,help="Pass --tags option to git ls-remote command.")
@click.option("--heads", "-h",is_flag=True,help="Pass --heads option to git ls-remote command.")
@click.option("--all/--first-only", "-a/-f",help="Try to run `git ls-remote` on all remotes.")
@click.option("--print-errors/--no-print-errors", "-e/-n",help="Print error messages.")
@click.pass_context
def ls_remote(ctx,name,remote,tags,heads,all,print_errors):
  '''
  Search for a project given by NAME and run `git ls-remote` on it.
  '''
  if not remote and not '/project/remotes' in ctx.obj:
    error(f"Did not find any remotes to look for {name} project in.")
    error(f"You need to either specify a remote to use with --remote url,")
    error(f"or add a section named /project/remotes that contains a list of remote urls,")
    error(f"to one of the project configuration files.")
    return 1
  
  if len(remote) < 1:
    remote = ctx.obj['/project/remotes']

  git = ctx.obj.get('/project/commands/git','git')

  for r in remote:
    parsed_url = urllib.parse.urlparse(r)
    if parsed_url.scheme in ['','file']:
        src = (Path(parsed_url.path)/name)
        try:
          cmd = [git,'ls-remote']
          if tags:
            cmd.append('--tags')
          if heads:
            cmd.append('--heads')
          cmd.append(str(src))
          output = subprocess.check_output(cmd,stderr=subprocess.STDOUT)
          sucess(f"Sucess: found project at {str(src)}.")
          info(output)
          if not all:
            break
        except subprocess.CalledProcessError as e:
          error(f"Did not find project at {str(src)}.")
          if print_errors:
            info(str(e))
            info(str(e.output.decode(encoding)))
        except Exception as e:
          error(f"Did not find project at {str(src)}.")
          if print_errors:
            info(str(e))
    else:
      error(f"Unknown scheme {parsed_url.scheme} in URL.")
      continue


@main.command(help="Tag current commit for release after running unit tests and any pre-release test scripts.")
@click.argument("tag")
@click.option("--dirty-ok","-d",is_flag=True,help="Don't error out if working directory is not clean.")
@click.option("--dry-run","-n",is_flag=True,help="Don't actually tag, just run checks.")
@click.pass_context
def tag_for_release(ctx,tag,dirty_ok,dry_run):


  git = ctx.obj.get('/project/commands/git','git')
  tags = subprocess.check_output([git,'tag']).decode(encoding).split('\n')
  if tag in tags:
    error(f"{tag} already exists. Choose another version number.")
    return 1

  if not dirty_ok:
    output = subprocess.check_output([git,'status','--porcelain'],encoding=encoding)
    if output != "":
      error(f"The working directory is not clean. Use --dirty-ok to tag anyway. Exiting now!")
      error(output)
      return 1

  root = get_project_root(Path())

  if (root/"version.txt").is_file():
    version_txt_tag = (root/"version.txt").read_text().strip()
    # if tag != version_txt_tag:
    #   error(f"{tag} does not match what was found in version.txt ({version_txt_tag}).")
    #   sys.exit(1)
    if not tag.startswith(version_txt_tag):
      error(f"{tag} does not begin with what was found in version.txt ({version_txt_tag}).")
      sys.exit(1)










  tdir = Path(tempfile.mkdtemp())
  ctx.obj['/project/build-dir'] = tdir
  ret = ctx.invoke(test,release=True)
  if ret != 0:
    error("Unit tests did not pass. Exiting now!")
    return 1

  hook_patterns = []
  if platform.system().lower() == "linux":
    hook_patterns = ["**/pre-tag-release.sh"]
  if platform.system().lower() == "windows":
    hook_patterns = ["**/pre-tag-release.bat"]
  for hook_pattern in hook_patterns:
    hooks = root.glob(hook_pattern)
    for hook in hooks:
      info(f"Running pre-rlease hook {str(hook)}")
      if not is_exe(hook):
        error(f"Found a pre-release hook '{hook}', but it is not executable.")
      res = subprocess.run([hook])
      if res.returncode != 0:
        error(f"Pre-release hook '{str(hook)}' failed. Exiting now!")
        return 1




  sucess("All tests passed. Tagging commit.")
  if not dry_run:
    subprocess.run([git,'tag',tag])


@main.command(help="Open a C++ project to start editing code. Only useful for IDE users.")
@click.option("--release","-r",help="Open the release build.")
@click.pass_context
def open(ctx,release):
  root = get_project_root(Path())
  build_dir = ctx.obj.get("/project/build-dir",None)
  if build_dir is None:
    build_dir = get_build_dir(Path(),release)
  else:
    build_dir = Path(build_dir)

  cmake = ctx.obj.get('/project/commands/cmake','cmake')
  ret = subprocess.run([cmake,'--open',build_dir])
  if ret.returncode == 1 and platform.system().lower() == "linux":
    vim = ctx.obj.get('/project/commands/vim','vim')
    ret = subprocess.run([vim,str(root)])


  return ret.returncode


class parsers:
  class Catch2:
    error_line = pp.LineStart() + pp.SkipTo(":")("filename") + pp.Literal(":") + pp.Word(pp.nums) + pp.Literal(": FAILED:")
  class UnitTestPlusPlus:
    error_line = pp.LineStart() + pp.SkipTo(":")("filename") + pp.Literal(":") + pp.Word(pp.nums) + pp.Literal(":") + pp.Word(pp.nums) + pp.Literal(": error:") + pp.SkipTo(pp.LineEnd())



@main.command(help="Parse parse and filter unit test output.")
@click.option("--path-filter","-p",multiple=True,help="Filter to apply to matched file paths.")
@click.pass_context
def filter_test_output(ctx,path_filter):
  for line in sys.stdin:
    line = line.strip("\n")
    def reroot_filename(s,l,t):
      for filter in path_filter:
        pat,repl = filter.split("|")
        result = re.sub(pat,repl,t[0])
        t[0] = result
      return t
    parsers.Catch2.error_line.setParseAction( reroot_filename )
    line = parsers.Catch2.error_line.transformString(line)
    parsers.UnitTestPlusPlus.error_line.setParseAction( reroot_filename )
    line = parsers.UnitTestPlusPlus.error_line.transformString(line)
    print(line)






  return 0




















def error(msg):
  click.echo(click.style(msg,fg='red'))

def sucess(msg):
  click.echo(click.style(msg,fg='green'))

def info(msg):
  click.echo(msg)

def get_project_root(path):
  try:
    dir = subprocess.check_output(["git","rev-parse","--show-toplevel"],cwd=path,stderr=subprocess.STDOUT)
  except:
    raise Exception(f"Could not determine project root directlry for {str(path)}")

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
    if platform.system().lower() == "linux":
      ret = subprocess.check_output(["file",str(path)])
      return ret.decode(encoding).find("with debug_info") > -1

  return False

def get_list_of_test_executables_in_path(path, patterns=None):
  if patterns is None:
    if platform.system().lower() == "linux":
      patterns = ["*Tests*", "*Tester*", "*unitTest*"]
    if platform.system().lower() == "windows":
      patterns = ["*Tests*.exe", "*Tester*.exe", "*unitTest*.exe"]


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

def get_build_dir(path,is_release,root_dir = None):
  build_type = get_build_type_str(is_release)
  if not root_dir:
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


def rmtree(dir):
  # shutil.rmtree(...) does not work on Windows all the time.
  # for file in path.glob('**'):
  #   if file.is_file():
  #     print(file)
  #   else:
  #     print(file)
  def del_rw(func,path,_):
    '''
    Clear the readonly bit on path and try to remove it.
    '''
    os.chmod(path, stat.S_IWRITE)
    s.remove(path)
  shutil.rmtree(dir, onerror=del_rw)

def load_environment( env ):
  '''
  Load a dictionary into the environment.

  Given a dictionary of key/value pairs, add keys to the environment with corresponding value.
  If the key already exists in the environment, then replace it.

  If a value contain a reference to the key (i.e. PATH : "some/path"${PATH:+:PATH}), then replace
  the reference with the current environment variable value.

  If a value is a list, convert it to a string using the OS environment variable list element separator.
  '''
  env_list_sep = ":"
  env_var_interp_patterns = ['${{{k}:+:${k}}}','${{{k}+:${k}}}']
  if platform.system().lower() == "windows":
    env_list_sep = ";"
    env_var_interp_patterns = ["$env:{k}"]

  for k in env:
    v = env[k]
    # if value is a list, then turn it into string
    if type(v) is list:
      v = env_list_sep.join(v) + env_list_sep + os.environ.get(k,'')

    # do shell interpolation...
    for pattern in env_var_interp_patterns:
      pattern = pattern.format(k=k)
      if k in os.environ:
        v = v.replace(pattern,env_list_sep+os.environ[k])
      else:
        v = v.replace(pattern,"")

    # clean...
    # we need to unquote elements in the lst
    v = env_list_sep.join( [ x.strip('"') for x in v.split(env_list_sep) ]    )

    os.environ[k] = v


def load_conan_environment(path):
  files_to_load = []
  if path.is_dir():
    ext = "sh"
    if platform.system().lower() == "windows":
      ext = "ps1"
    files_to_load = path.glob(f'environment*.{ext}.env')
  else:
    files_to_load.append(path)

  for file in files_to_load:
    vars = configparser
    env = configparser.ConfigParser(allow_no_value=True,interpolation=None,delimiters=('=',))
    env.optionxform=str # don't convert keys to lowercase
    text = '[ENV]\n' + file.read_text()
    env.read_string(text)

    load_environment(env['ENV'])



def load_conan_buildinfo(path):
  if path.is_dir():
    path = path / 'conanbuildinfo.txt'
    if not path.exists():
      return

  info = configparser.ConfigParser(allow_no_value=True,interpolation=None,delimiters=('=',))
  info.optionxform=str # don't convert keys to lowercase
  info.read(path)
  env_sections = list(filter( lambda s : s.startswith("ENV_"), info.sections() ))

  for section in env_sections:
    env = dict()
    for k in info[section]:
      v = info[section][k]
      if v.startswith('['):
        v = json.loads(v.replace("\\","\\\\"))
      env[k] = v
    load_environment(env)










def merge(a, b, path=None):
  '''Merge nested dictionary 'b' into dictionary 'a'.'''
  if path is None: path = []
  for key in b:
      if key in a:
          if isinstance(a[key], dict) and isinstance(b[key], dict):
              merge(a[key], b[key], path + [str(key)])
          elif a[key] == b[key]:
              pass # same leaf value
          else:
              raise Exception('Conflict at %s' % '.'.join(path + [str(key)]))
      else:
          a[key] = b[key]
  return a


class NewProjectBuilder:
  def __init__(self,name,dir=Path('.'),type='exe'):
    dir = Path(dir)
    self.name = name
    self.type = type
    self.root = dir/name
    missing = self.check_for_system_tools()
    if missing > 0:
      raise Exception(f"Could not find {missing} of the system tools needed (See above). Please install them and try again")

  def setup_layout(self):
    if self.root.exists():
      raise Exception(f"Cannot create project directory {str(self.root)}, it already exists.")
    self.root.mkdir()


  def check_for_system_tools(self):
    self.cmake = shutil.which("cmake")
    self.conan = shutil.which("conan")
    self.git = shutil.which("git")

    missing = 0
    if self.cmake is None:
      missing += 1
      error("No Cmake executable was found.")
    if self.conan is None:
      missing += 1
      error("No Conan executable was found.")
    if self.git is None:
      missing += 1
      error("No git executable was found.")

    return missing

  def get_system_tool(self,tool):
    pass



  def setup_cmake(self):
    pass
  def setup_conan(self):
    pass
  def setup_docs(self):
    pass
  def setup_tests(self):
    pass
  def setup_source(self):
    pass
  def setup_git(self):
    gitignore = self.root/".gitignore"
    gitignore.write_text('''
build*/ # build directoreis
.*.swp  # vim swap files
*~      # emacs backup files
.cland/ # clangd language server database
compile_commands.json # clang compile command database
''')
    subprocess.run([self.git,"init"],cwd=self.root)
    subprocess.run([self.git,"add","."],cwd=self.root)
    subprocess.run([self.git,"commit","-m","initial import"],cwd=self.root)


  def setup(self):
    self.setup_layout()
    self.setup_source()
    self.setup_conan()
    self.setup_cmake()
    self.setup_docs()
    self.setup_tests()
    self.setup_git()





  def get_installed_cmake_version(self):
    ret = subprocess.check_output([self.cmake,'--version']).decode(encoding)
    version = re.match("cmake version ([0-9]\.[0-9]\.[0-9]).*\n",ret)
    version = re.match("cmake version ([0-9]+\.[0-9]+\.[0-9]+)",ret)[1]
    return version

class PFLBuilder(NewProjectBuilder):
  def __init__(self,name,dir):
    super().__init__(name,dir)

    self.src_dir = self.root/'src'
    self.tests_dir = self.root/'tests'
    self.docs_dir = self.root/'docs'
    self.data_dir = self.root/'data'
    self.examples_dir = self.root/'examples'
    self.tools_dir = self.root/'tools'

    self.toplevel_cmakelists = self.root/"CMakeLists.txt"
    self.tests_cmakelists = self.tests_dir/"CMakeLists.txt"


  def setup_layout(self):
    super().setup_layout()

    self.src_dir.mkdir()
    self.tests_dir.mkdir()
    self.docs_dir.mkdir()
    self.data_dir.mkdir()
    self.examples_dir.mkdir()
    self.tools_dir.mkdir()

  def setup_cmake(self):
    cmake_minimum_version = '.'.join(self.get_installed_cmake_version().split('.')[0:2])
    chunks = list()
    chunks.append(
f'''
cmake_minimum_required(VERSION {cmake_minimum_version})
project({self.name})
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

include(${{CMAKE_BINARY_DIR}}/conanbuildinfo.cmake)
conan_basic_setup(TARGETS)
''')
    if self.type == 'exe':
      chunks.append(f'''
add_executable( {self.name} )
target_sources( {self.name} PUBLIC src/main.cpp ) 
target_compile_features( {self.name} PUBLIC cxx_std_17 )
target_link_libraries( {self.name} ${{CONAN_LIBS}} )
''')

    chunks.append(
f'''
install(TARGETS {self.name}
  EXPORT {self.name}Targets
  LIBRARY DESTINATION lib
  ARCHIVE DESTINATION lib
  RUNTIME DESTINATION bin
  INCLUDES DESTINATION include)
''')


    self.toplevel_cmakelists.write_text('\n'.join(chunks))


  def setup_conan(self):
    conanfile = self.root/"conanfile.txt"
    conanfile.write_text(
    '''[requires]
# put dependencies here
# examples:
# boost/1.70.0
[generators]
cmake
virtualenv
'''
    )


  def setup_source(self):
    if self.type == 'exe':
      main_cpp = self.src_dir/'main.cpp'
      main_cpp.write_text(
'''
#include <iostream>

int main(int argc,char* argv[])
{
  std::cout << "Hello World" << std::endl;
}
'''
)
    elif self.type == 'lib':
      lib_cpp = self.src_dir/f'{self.name}.cpp'
      lib_h   = self.src_dir/f'{self.name}.hpp'
      lib_h.write_text(
f'''
#include <string>

std::string version();
f'''
)
      lib_cpp.write_text(
'''
#include "./{self.name}.hpp"

std::string version()
{
  return "0.1";
}
'''
)
    else:
      Exception(f"Unrecognized project type '{self.type}'. Should be 'exe' or 'lib'.")


  def setup_docs(self):

    readme = self.root / "README.md"
    readme.write_text(
f'''# {self.name}
A short description of the project

## Building/Installing

To build the project, create a build directory, install the dependencies with Conan, and then and use CMake.
```
$ mkdir build
$ cd build
$ conan install .. --build missing
$ cmake ..
$ cmake --build .
```

or use `ccc build`
```
$ ccc build
```

To install, specify the install prefix and run the `install` target
```
$ mkdir build
$ cd build
$ conan install .. --build missing
$ cmake .. -DCMAKE_INSTALL_PREFIX=/directory/to/install
$ cmake --build . --target install
```

or use `ccc install`
```
$ ccc install /path/to/install
```

## Usage

Document basic usage here.
''')


