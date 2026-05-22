"""list — list AWS resources by type, filter by tag / missing-tag.

WHAT YOU MUST BUILD
-------------------
Support 4 resource types: ec2, rds, s3, volume.
Each takes:
- `want` — list of (key, value) tag pairs the resource MUST have
- `missing` — list of tag keys the resource MUST NOT have

Print a formatted table to stdout. Test cases are in tests/test_list.py.

HELPERS YOU CAN USE
-------------------
From commands._common:
  parse_kv(s) -> (k, v)            # "Owner=alice" -> ("Owner", "alice")
  tags_to_dict(items) -> dict       # boto3 [{"Key","Value"}] -> {k: v}
  tags_match(tags, want, missing) -> bool

AWS APIS YOU'LL NEED
--------------------
- EC2: ec2.describe_instances() with get_paginator
- RDS: rds.describe_db_instances(), then list_tags_for_resource(ResourceName=arn)
- S3:  s3.list_buckets(), then get_bucket_tagging(Bucket=name)
       (catch ClientError when bucket has no tagging config — treat as {})
- EBS: ec2.describe_volumes() with get_paginator

EXPECTED OUTPUT FORMAT (when run from CLI)
------------------------------------------
    EC2 Environment=dev — 1 found:
    ------------------------------------------------------------------------------
      i-0abc123def456789a       t3.micro       running       Environment=dev

VERIFY
------
    pytest tests/test_list.py -v
"""
import boto3
from botocore.exceptions import ClientError

from commands._common import parse_kv, tags_to_dict, tags_match


def _list_ec2(want, missing):
    """List EC2 instances matching tag filters.

    Args:
        want: list of (key, value) tag pairs that must all match
        missing: list of tag keys that must NOT be present

    Returns:
        list of (instance_id, instance_type, state, tags_dict) tuples
    """
    ec2 = boto3.client("ec2")
    paginator = ec2.get_paginator("describe_instances")
    rows = []
    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                iid = instance["InstanceId"]
                itype = instance["InstanceType"]
                state = instance["State"]["Name"]
                tags = tags_to_dict(instance.get("Tags", []))
                if tags_match(tags, want, missing):
                    rows.append((iid, itype, state, tags))
    return rows


def _list_rds(want, missing):
    """Same shape as _list_ec2 but for RDS DB instances.

    Note: RDS tags require a separate API call per DB:
        rds.list_tags_for_resource(ResourceName=db['DBInstanceArn'])

    Returns:
        list of (db_id, db_class, db_status, tags_dict) tuples
    """
    rds = boto3.client("rds")
    paginator = rds.get_paginator("describe_db_instances")
    rows = []
    for page in paginator.paginate():
        for db in page.get("DBInstances", []):
            db_id = db["DBInstanceIdentifier"]
            db_class = db["DBInstanceClass"]
            db_status = db["DBInstanceStatus"]
            db_arn = db["DBInstanceArn"]
            try:
                tags_resp = rds.list_tags_for_resource(ResourceName=db_arn)
                tags = tags_to_dict(tags_resp.get("TagList", []))
            except ClientError:
                tags = {}
            if tags_match(tags, want, missing):
                rows.append((db_id, db_class, db_status, tags))
    return rows


def _list_s3(want, missing):
    """List S3 buckets matching tag filters.

    Note: get_bucket_tagging raises ClientError if no tagging config exists
    for that bucket. Treat that as an empty tags dict, not an error.

    Returns:
        list of (bucket_name, "bucket", "active", tags_dict) tuples
    """
    s3 = boto3.client("s3")
    buckets_resp = s3.list_buckets()
    rows = []
    for bucket in buckets_resp.get("Buckets", []):
        name = bucket["Name"]
        try:
            tagging_resp = s3.get_bucket_tagging(Bucket=name)
            tags = tags_to_dict(tagging_resp.get("TagSet", []))
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchTagSet", "NoSuchBucketTagging"):
                tags = {}
            else:
                raise
        if tags_match(tags, want, missing):
            rows.append((name, "bucket", "active", tags))
    return rows


def _list_volume(want, missing):
    """List EBS volumes matching tag filters.

    Returns:
        list of (volume_id, "<type>-<size>GB", state, tags_dict) tuples
        e.g. ("vol-0abc", "gp2-100GB", "in-use", {"purpose": "practice"})
    """
    ec2 = boto3.client("ec2")
    paginator = ec2.get_paginator("describe_volumes")
    rows = []
    for page in paginator.paginate():
        for vol in page.get("Volumes", []):
            vid = vol["VolumeId"]
            vtype = vol["VolumeType"]
            size = vol["Size"]
            state = vol["State"]
            tags = tags_to_dict(vol.get("Tags", []))
            if tags_match(tags, want, missing):
                type_size = f"{vtype}-{size}GB"
                rows.append((vid, type_size, state, tags))
    return rows


DISPATCH = {
    "ec2": _list_ec2,
    "rds": _list_rds,
    "s3": _list_s3,
    "volume": _list_volume,
}


def run(args):
    """Entry point called by costctl.py.

    Steps you should perform:
      1. Convert args.tag (list of "k=v" strings) → want pairs via parse_kv
      2. Use args.missing_tag (list of keys) as-is
      3. Call DISPATCH[args.type](want, missing) → rows
      4. Print a header line, separator, then one row per resource

    Args set by argparse:
        args.type         — one of "ec2", "rds", "s3", "volume"
        args.tag          — list[str], each "key=value"
        args.missing_tag  — list[str], each "key"
    """
    want = [parse_kv(t) for t in args.tag]
    missing = args.missing_tag
    rows = DISPATCH[args.type](want, missing)

    filters = []
    if args.tag:
        filters.extend(args.tag)
    if args.missing_tag:
        filters.extend(f"missing-{k}" for k in args.missing_tag)

    filter_str = f" {','.join(filters)}" if filters else ""
    print(f"{args.type.upper()}{filter_str} — {len(rows)} found:")
    print("-" * 78)
    for r_id, r_type, r_state, r_tags in rows:
        tags_str = ", ".join(f"{k}={v}" for k, v in r_tags.items())
        print(f"  {r_id:<25} {r_type:<14} {r_state:<13} {tags_str}")
