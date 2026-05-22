"""clean — (stretch) bulk terminate resources matching a tag.

WARNING — DESIGN-FOR-SAFETY
---------------------------
This is the most dangerous command in the CLI. Get the contract right:

  1. DEFAULT IS DRY-RUN. Without --apply the command MUST NOT touch resources.
     It only lists what WOULD be deleted.
  2. Even with --apply, you should consider printing a summary count first
     ("about to terminate N EC2 + M volumes — proceed?"), though for this
     starter a hard `--apply` flag is enough.
  3. Never use this with a tag you don't fully own. Reflection prompt in
     README covers the blast-radius scenario.

WHAT YOU MUST BUILD
-------------------
1. `_find_targets(tag_key, tag_val)` — return a dict like:
     {"ec2": [<instance ids in non-terminal state>],
      "volume": [<volume ids in 'available' state only>]}
   Skip terminated/shutting-down instances (already gone).
   Skip in-use volumes (can't delete while attached — would error anyway).

2. `run(args)` — call _find_targets, print the plan, then either:
     - bail with "(dry-run — pass --apply to ...)"  (default)
     - or actually terminate (when --apply)

HELPERS YOU CAN USE
-------------------
From commands._common:
  parse_kv(s) -> (k, v)
  tags_to_dict(items) -> dict
  tags_match(tags, want, missing) -> bool

AWS APIS YOU'LL NEED
--------------------
- ec2.describe_instances() + describe_volumes() — same as list_cmd
- ec2.terminate_instances(InstanceIds=[...])
- ec2.delete_volume(VolumeId=...)  (per volume, no bulk API)

VERIFY
------
    pytest tests/test_clean.py -v
"""
import boto3

from commands._common import parse_kv, tags_to_dict, tags_match


def _find_targets(tag_key, tag_val):
    """Return {"ec2": [...], "volume": [...]} matching tag in non-terminal state."""
    ec2 = boto3.client("ec2")
    targets = {"ec2": [], "volume": []}
    
    # 1. Find non-terminal EC2 instances
    paginator_ec2 = ec2.get_paginator("describe_instances")
    for page in paginator_ec2.paginate():
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                iid = instance["InstanceId"]
                state = instance["State"]["Name"]
                tags = tags_to_dict(instance.get("Tags", []))
                if tags_match(tags, [(tag_key, tag_val)], []):
                    if state not in ("terminated", "shutting-down"):
                        targets["ec2"].append(iid)
                        
    # 2. Find available EBS volumes
    paginator_vol = ec2.get_paginator("describe_volumes")
    for page in paginator_vol.paginate():
        for vol in page.get("Volumes", []):
            vid = vol["VolumeId"]
            state = vol["State"]
            tags = tags_to_dict(vol.get("Tags", []))
            if tags_match(tags, [(tag_key, tag_val)], []):
                if state == "available":
                    targets["volume"].append(vid)
                    
    return targets


def run(args):
    """Entry point.

    Args set by argparse:
        args.tag    — "key=value" string (REQUIRED)
        args.apply  — bool, must be True to actually delete (default False = dry-run)
    """
    tag_key, tag_val = parse_kv(args.tag)
    targets = _find_targets(tag_key, tag_val)
    
    if not targets["ec2"] and not targets["volume"]:
        print("Nothing to clean.")
        return
        
    if not args.apply:
        print(f"Would terminate {len(targets['ec2'])} EC2 instance(s) and delete {len(targets['volume'])} EBS volume(s).")
        print(f"(dry-run — pass --apply to clean resources)")
    else:
        ec2 = boto3.client("ec2")
        if targets["ec2"]:
            ec2.terminate_instances(InstanceIds=targets["ec2"])
            print(f"Terminated EC2 instance(s): {', '.join(targets['ec2'])}")
        if targets["volume"]:
            for vid in targets["volume"]:
                ec2.delete_volume(VolumeId=vid)
            print(f"Deleted EBS volume(s): {', '.join(targets['volume'])}")
