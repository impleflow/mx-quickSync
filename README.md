# Quick Sync for Manage (part of IBM MAS)

Pushes locally compiled Java classes (`businessobjects`, `maximouiweb`) straight into a running Manage pod,
so you do not have to deploy new customization zip after every change. 

No build, no deploy, no pod restart. Only WebSphere Liberty inside the running `<env>-<env>-all` pod needs to reload the Manage application.

## How does it work

1. Logs in to OpenShift with `oc` (into a temporary kubeconfig; your current `oc` context is untouched).
2. Finds the pod of the running Manage instance.
3. Unpacks the EAR on the pod (skipped if `/tmp/maximo.unpack` already exists), copies your compiled classes into
   the unpacked modules and repacks it to `/tmp/maximo.ear`.
4. Replaces the live EAR (as root, via `oc debug node` on the cluster node that runs the pod). Liberty then reloads
   the Manage application - wait for it (5-10 minutes). 
5. The changes remain available until the pod is restarted. The pod will then start from its original image, without the changes made by this script.

## Limitations

Supports only environments whose server bundles consist of a single bundle of type `all` with pod count `1`.
Other bundle types (`cron`, `ui`, ...) and multiple pods are not supported.

After reinitialization of manage application the menu could not be visible. You will be able to still access start page. To handle it see Known Errors.

## Requirements

- Python 3.11+ and `pip install -r requirements.txt` (PyYAML)
- `oc` CLI in `PATH`, permission to `oc debug node` on the cluster; `sops` only if you use an encrypted `secrets.yaml`
- compiled classes in your MAS sources directory (`maximo_smp_dir`)

## Configuration

Create your configuration files from the examples (`config.yaml.example`, `local.yaml.example`) and fill them in;
the keys, including the `oc` login, are described there.

The script reads these files:

1. `config.yaml` - shared configuration that can be safely stored in git
2. `secrets.yaml` - optional, for sops-encrypted values (requires `sops` in `PATH`)
3. `local.yaml` - optional, for personal values that must not go to git

Each next file overrides the values from the previous one. The files are searched for in the script directory and
in the directory the script is run from, including their parent directories up to the one containing `.git`.


## Usage

```
python quickSync/quickSync.py <env>                        # <env>: key under environments: in config.yaml, e.g. dev
python quickSync/quickSync.py <env> --pod <full-pod-name>  # when the prefix matches more than one pod
```

## Known Errors

After Liberty reloads the application, Manage can disappear from the menu (the `ROUTER` cache stays empty) until
the pod is restarted. To fix it, run `MXServer.getMXServer().reloadMaximoCache("ROUTER", true);` in your code,
e.g. by adding a service based on [XQuickSync.java](java/XQuickSync.java).

## License

GPL-3.0-or-later, Copyright (C) 2026 Impleflow Sp. z o.o. See `LICENSE`.
