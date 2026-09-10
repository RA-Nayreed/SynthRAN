"""Render deployment inventory and the upstream Ansible execution context."""
import copy, json, os, re, shutil, socket, sys, yaml
from synthran.r2lab import access
from pathlib import Path
from synthran.deployment_state import build_manifest, build_ue_map
c=yaml.safe_load(Path(sys.argv[1]).read_text()); d=c['deployment']; nodes=d['nodes']; ues=d['ues']
workload_only=sys.argv[3] == 'true'
resume_source_contract=sys.argv[4]
if len(ues) != len(set(ues)): raise SystemExit('UE names must be unique: ' + ', '.join(ues))
# Preserve the upstream 100-port spacing while allowing every representable
# pair. This is a TCP port-space guard, not the inherited three-UE policy.
if d['ran'].lower() == 'srsran' and d['platform'] == 'rfsim' and len(ues) > 635:
    raise SystemExit('srsRAN RFSIM exceeds the available TCP port range (maximum 635 UEs)')
if d['platform'] == 'r2lab' and d['ran'].lower() == 'ueransim': raise SystemExit('UERANSIM cannot be combined with an R2Lab physical radio')
profile_name=d.get('profile','default')
profile_source=Path(d.get('profile_file') or Path('deployment/group_vars/all', f'5g_profile_{profile_name}.yaml'))
if not profile_source.is_file():
    raise SystemExit(f'5G profile not found: {profile_source}')
profile=yaml.safe_load(profile_source.read_text())
available_ues=profile.get('ues', {})
overrides=d.get('ue_profiles', {})
slice_names=[entry['name'] for entry in profile.get('slices', [])]
if not slice_names:
    raise SystemExit(f'5G profile {profile_name!r} defines no slices')
selected_ues={}
if not isinstance(overrides, dict):
    raise SystemExit('deployment.ue_profiles must be a mapping when provided')
for name in ues:
    if name in available_ues:
        ue_profile=copy.deepcopy(available_ues[name])
    elif name in overrides:
        ue_profile={}
    elif d['platform'] == 'rfsim' and d['ran'].lower() == 'srsran':
        match=re.fullmatch(r'uesim([0-9]+)', name)
        if not match or int(match.group(1)) < 1:
            raise SystemExit(
                f"Software UE {name!r} is absent from {profile_source}; "
                "define it there or use a name such as uesim04"
            )
        suffix_value=1120 + int(match.group(1))
        if suffix_value > 9_999_999_999:
            raise SystemExit(f'Cannot derive a 10-digit IMSI suffix for {name!r}')
        ue_profile={'imsi_suffix': f'{suffix_value:010d}', 'slice': slice_names[0]}
    elif d['platform'] == 'r2lab':
        raise SystemExit(f'Physical UE {name!r} is absent from {profile_source}')
    else:
        raise SystemExit(
            f"Software UE {name!r} is absent from {profile_source}; "
            f"automatic UE generation is supported by the srsRAN RFSIM backend, not {d['ran']}"
        )
    ue_profile.update(copy.deepcopy(overrides.get(name, {})))
    suffix=str(ue_profile.get('imsi_suffix', ''))
    if not re.fullmatch(r'[0-9]{10}', suffix):
        raise SystemExit(f'UE {name!r} must have a 10-digit imsi_suffix, got {suffix!r}')
    if ue_profile.get('slice') not in slice_names:
        raise SystemExit(
            f"UE {name!r} references unknown slice {ue_profile.get('slice')!r}; "
            f"available slices: {', '.join(slice_names)}"
        )
    ue_profile['imsi_suffix']=suffix
    selected_ues[name]=ue_profile
suffix_owners={}
for name, ue_profile in selected_ues.items():
    suffix_owners.setdefault(ue_profile['imsi_suffix'], []).append(name)
duplicates={suffix:names for suffix,names in suffix_owners.items() if len(names) > 1}
if duplicates:
    raise SystemExit('Selected UEs have duplicate IMSI suffixes: ' + repr(duplicates))
profile=copy.deepcopy(profile)
profile['ues']=selected_ues
ue_map=build_ue_map(c, profile)
# Upstream delegates to this inventory name; an alias such as faraday_host
# silently loses the configured connection variables on delegated tasks.
children = {}
for group, name in [('core_node', nodes['core']), ('ran_node', nodes['ran']), ('broker_node', nodes.get('broker', nodes['core']))]:
    address = d.get('host_vars', {}).get(name, {}).get('ip') or socket.gethostbyname(name)
    children[group] = {'hosts': {name: {'ip': address, 'ansible_python_interpreter': '/usr/bin/python3', **d.get('host_vars', {}).get(name, {})}}}
children['sopnodes'] = {'children': {'core_node': {}, 'ran_node': {}}}
children['k8s_workers'] = {'children': {'ran_node': {}}}
children['physical_ues'] = {'hosts': {}}
children['faraday'] = {'hosts': {}}
if d['platform'] == 'r2lab':
    import shlex
    settings = access(d)
    ssh = ['ssh']
    if settings['identity_file']:
        ssh += ['-i', settings['identity_file']]
    target = (settings['username'] + '@' if settings['username'] else '') + settings['host']
    proxy = shlex.join(ssh + ['-W', '%h:%p', target])
    faraday_vars = {'ansible_host': settings['host'], 'ansible_python_interpreter': '/usr/bin/python3'}
    if settings['username']:
        faraday_vars['ansible_user'] = settings['username']
    if settings['identity_file']:
        faraday_vars['ansible_ssh_private_key_file'] = settings['identity_file']
    children['faraday']['hosts']['faraday.inria.fr'] = faraday_vars
    for group in ('qhats', 'qfits'):
        children[group] = {'hosts': {}}
    for ue in ue_map:
        name = ue['device']
        group = 'qhats' if name.startswith('qhat') else 'qfits' if name.startswith('qfit') else None
        if group is None:
            raise SystemExit(f'Upstream R2Lab modem workflow requires a qhat or qfit host: {name}')
        host = {'ansible_user': 'root', 'ansible_python_interpreter': '/usr/bin/python3',
                'ansible_ssh_common_args': '-o ' + shlex.quote('ProxyCommand=' + proxy),
                'mode': ue['tunnel']['mode']}
        if settings['identity_file']:
            host['ansible_ssh_private_key_file'] = settings['identity_file']
        host.update(d.get('host_vars', {}).get(name, {}))
        children[group]['hosts'][name] = host
    children['physical_ues'] = {'children': {'qhats': {}, 'qfits': {}}}
elif d['platform'] == 'physical':
    children['physical_ues']['hosts'] = {name: d.get('host_vars', {}).get(name, {}) for name in ues}
Path(sys.argv[2], 'inventory.yml').write_text(yaml.safe_dump({'all': {'children': children}}, sort_keys=False))
effective_profile_path=Path(sys.argv[2], 'fiveg-profile.yml')
effective_profile_path.write_text(yaml.safe_dump(profile, sort_keys=False))
topology_source=Path(d.get('topology_file', 'deployment/topology.yml'))
topologies=yaml.safe_load(topology_source.read_text())
try:
    topology=copy.deepcopy(topologies['rans'][d['ran'].lower()][d['core'].lower()])
except KeyError as error:
    raise SystemExit(f"No asserted topology contract for {d['ran']} + {d['core']}") from error
if d['ran'].lower() == 'srsran' and d['core'].lower() == 'free5gc':
    n2=topology['network']['n2']
    endpoint='amf_ip_colocated' if nodes['core'] == nodes['ran'] else 'amf_ip_split'
    n2['amf_ip']=n2[endpoint]
    n2.pop('amf_ip_colocated')
    n2.pop('amf_ip_split')
topology['contract_version']=topologies['schema_version']
manifest=build_manifest(c, profile, ue_map, topology)
manifest_path=Path(sys.argv[2], 'deployment-fingerprint.json')
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
variables={'synthran_root':str(Path.cwd()),'core':d['core'],'ran':'srsRAN' if d['ran'].lower() == 'srsran' else d['ran'],'rru':'rfsim' if d['platform']=='rfsim' else d.get('ru',d['platform']),'platform':d['platform'],'fiveg_profile':'resolved','fiveg_profile_file':str(effective_profile_path.resolve()),'core_node_name':nodes['core'],'ran_node_name':nodes['ran'],'broker_node_name':nodes.get('broker',nodes['core']),'bridge_enabled':d.get('bridge_enabled',True),'open5gs_webui_enabled':d.get('open5gs_webui_enabled',False),'fhi72':False,'f3_ran':False,'aw2s':False,'run_dir':str(Path(sys.argv[2]).resolve()),'scenario_file':str(Path(sys.argv[1]).resolve()),'ue_count':len(ues),'synthran_ue_map':ue_map,'synthran_topology':topology,'synthran_deployment_contract':manifest,'synthran_deployment_contract_file':str(manifest_path.resolve()),'synthran_workload_only':workload_only}
if resume_source_contract:
    variables['synthran_resume_source_contract']=json.loads(Path(resume_source_contract).read_text())
Path(sys.argv[2],'deployment-vars.yml').write_text(yaml.safe_dump(variables,sort_keys=False))
# Supply the resolved profile at the exact relative path expected by upstream
# roles, without patching those files or rewriting the repository's profiles.
context = Path(sys.argv[2], 'ansible')
shutil.copytree('deployment/playbooks', context / 'playbooks', dirs_exist_ok=True)
shutil.copytree('deployment/group_vars', context / 'group_vars', dirs_exist_ok=True)
shutil.copyfile(effective_profile_path, context / 'group_vars/all/5g_profile_resolved.yaml')

(context / 'roles').symlink_to(Path('deployment/roles').resolve(), target_is_directory=True)
