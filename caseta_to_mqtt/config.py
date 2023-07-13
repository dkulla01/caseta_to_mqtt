from dynaconf import Dynaconf

settings = Dynaconf(
    root_path="caseta_to_mqtt/",
    envvar_prefix="DYNACONF",
    environments=True,
    settings_files=["settings.toml", ".secrets.toml"],
)

# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.
