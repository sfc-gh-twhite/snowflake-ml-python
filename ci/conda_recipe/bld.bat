@echo off
setlocal EnableDelayedExpansion

bazel "--output_user_root=C:\broot" "build" "--repository_cache=" "--nobuild_python_zip" "--enable_runfiles" --action_env="USERPROFILE=%USERPROFILE%" --host_action_env="USERPROFILE=%USERPROFILE%" "//snowflake/ml:wheel"
SET BAZEL_BIN_PATH=
FOR /f "delims=" %%a in ('bazel --output_user_root=C:\broot info bazel-bin') DO (SET "BAZEL_BIN_PATH=!BAZEL_BIN_PATH!%%a")
SET WHEEL_PATH_PATTERN="!BAZEL_BIN_PATH:/=\!\snowflake\ml\*.whl"
SET WHEEL_PATH=
FOR /f "delims=" %%a in ('dir /b/s !WHEEL_PATH_PATTERN!') DO (SET "WHEEL_PATH=!WHEEL_PATH!%%a")
pip "install" "--no-dependencies" "!WHEEL_PATH!"
bazel "clean" "--expunge"
bazel "shutdown"
