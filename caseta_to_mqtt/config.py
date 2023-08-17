from dynaconf import Dynaconf


# you should create settings files and tell dynaconf about them with an env var
# export SETTINGS_FILES_FOR_DYNACONF="['path/to/your/file.toml', ...]"
settings = Dynaconf(environments=True)
