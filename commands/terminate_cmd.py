"""terminate — terminate or delete one resource, with safety confirmation.

WHAT YOU MUST BUILD
-------------------
4 dispatch functions, one per resource type, that:
  - Ask `confirm(...)` before doing the destructive call (unless --force)
  - Perform the right boto3 API call
  - Handle ClientError gracefully (no stack trace dump)

Safety contract — DO NOT break this:
  - `terminate` MUST ask y/N confirmation by default
  - `--force` bypasses confirm (for CI / scripted use)
  - S3 MUST refuse to delete buckets that still contain objects
  - Any AWS error MUST print a friendly message, not a Python traceback

HELPERS YOU CAN USE
-------------------
From commands._common:
  confirm(prompt, force=False) -> bool
    # If force=True, returns True. Otherwise asks "<prompt> [y/N] " on stdin.

AWS APIS YOU'LL NEED
--------------------
- EC2: ec2.terminate_instances(InstanceIds=[id])
- RDS: rds.stop_db_instance(DBInstanceIdentifier=id)  # full delete needs final snapshot
- S3:  s3.list_objects_v2(Bucket=name).get("KeyCount", 0)  # check empty first
       s3.delete_bucket(Bucket=name)
- EBS: ec2.delete_volume(VolumeId=id)

ERROR HANDLING
--------------
Wrap the dispatch call in `try: ... except ClientError as e: print(...)`. Extract
e.response["Error"]["Code"] and e.response["Error"]["Message"] for the message.

EXPECTED OUTPUT
---------------
On success:
    Terminated EC2 i-0abc123

On user abort:
    Aborted.

On refuse (S3 non-empty):
    Refusing — bucket my-bucket has 12 object(s). Empty it first.

On AWS error:
    AWS error [InvalidInstanceID.NotFound]: The instance ID 'i-xxx' does not exist

VERIFY
------
    pytest tests/test_terminate.py -v
"""
import boto3
from botocore.exceptions import ClientError

from commands._common import confirm


def _terminate_ec2(rid, force):
    """Terminate one EC2 instance after confirmation."""
    if confirm(f"Terminate EC2 instance {rid}?", force):
        ec2 = boto3.client("ec2")
        ec2.terminate_instances(InstanceIds=[rid])
        print(f"Terminated EC2 {rid}")
    else:
        print("Aborted.")


def _terminate_rds(rid, force):
    """Stop one RDS instance after confirmation.

    Full delete (delete_db_instance) requires a final snapshot decision —
    out of scope for this challenge. Stop is enough to stop billing.
    """
    if confirm(f"Stop RDS DB instance {rid}?", force):
        rds = boto3.client("rds")
        rds.stop_db_instance(DBInstanceIdentifier=rid)
        print(f"Stopped RDS {rid}")
    else:
        print("Aborted.")


def _terminate_s3(rid, force):
    """Delete one S3 bucket — refuse if it has any objects."""
    s3 = boto3.client("s3")
    resp = s3.list_objects_v2(Bucket=rid)
    count = resp.get("KeyCount", 0)
    # Fallback/double check for Content length if KeyCount is 0 or missing
    if count == 0 and "Contents" in resp:
        count = len(resp["Contents"])

    if count > 0:
        print(f"Refusing — bucket {rid} has {count} object(s). Empty it first.")
        return

    if confirm(f"Delete S3 bucket {rid}?", force):
        s3.delete_bucket(Bucket=rid)
        print(f"Deleted S3 bucket {rid}")
    else:
        print("Aborted.")


def _terminate_volume(rid, force):
    """Delete one EBS volume after confirmation."""
    if confirm(f"Delete EBS volume {rid}?", force):
        ec2 = boto3.client("ec2")
        ec2.delete_volume(VolumeId=rid)
        print(f"Deleted EBS volume {rid}")
    else:
        print("Aborted.")


DISPATCH = {
    "ec2": _terminate_ec2,
    "rds": _terminate_rds,
    "s3": _terminate_s3,
    "volume": _terminate_volume,
}


def run(args):
    """Entry point.

    Args set by argparse:
        args.type   — one of "ec2", "rds", "s3", "volume"
        args.id     — resource identifier
        args.force  — bool, skip confirm if True
    """
    try:
        DISPATCH[args.type](args.id, args.force)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        print(f"AWS error [{code}]: {msg}")
