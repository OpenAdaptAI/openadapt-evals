"""AWS VM operations for WAA benchmark evaluation.

Provides a Python API for EC2 instance lifecycle management using boto3.
Implements the VMProvider protocol so PoolManager can use AWS identically
to Azure.

Requires: pip install boto3  (or: uv sync --extra aws)

Auth uses boto3's default credential chain:
    1. Environment variables (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY)
    2. Shared credentials file (~/.aws/credentials)
    3. AWS config file (~/.aws/config)
    4. Instance metadata (on EC2)

Example:
    from openadapt_evals.infrastructure.aws_vm import AWSVMManager

    vm = AWSVMManager(region="us-east-1")
    info = vm.create_vm("waa-pool-00", region="us-east-1", size="m5.2xlarge")
    ip = vm.get_vm_ip("waa-pool-00")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Instance types with nested virtualization (KVM) support.
# WAA requires QEMU/KVM, which only bare-metal instances expose on AWS.
# m5.metal: 96 vCPU, 384GB — supports /dev/kvm for nested virtualization.
INSTANCE_TYPE = "m5.metal"
INSTANCE_TYPE_FALLBACKS = [
    ("m5.metal", 4.608),
    ("m5n.metal", 5.712),
    ("c5.metal", 4.080),
    ("m5a.xlarge", 0.172),  # Non-KVM fallback (won't run QEMU, for testing only)
]
# Regions to try in order of preference
AWS_REGIONS = ["us-east-1", "us-west-2", "us-east-2", "eu-west-1"]

# Ubuntu 22.04 LTS AMI name pattern (Canonical official)
_UBUNTU_AMI_NAME = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
_UBUNTU_AMI_OWNER = "099720109477"  # Canonical

# Tag used to identify pool resources
_POOL_TAG_KEY = "waa-pool"


def _default_region() -> str:
    """Get default AWS region from config or environment."""
    try:
        from openadapt_evals.config import settings

        return settings.aws_region
    except Exception:
        import os

        return os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


@dataclass
class AWSVMManager:
    """Manages AWS EC2 instances for WAA benchmark evaluation.

    Uses boto3 for all AWS operations.

    Args:
        region: AWS region for instance operations.
    """

    region: str = field(default_factory=_default_region)

    def __post_init__(self) -> None:
        self._ec2_client = None
        self._ec2_resource = None

    def _get_ec2_client(self):
        """Lazy-load boto3 EC2 client."""
        if self._ec2_client is None:
            import boto3

            self._ec2_client = boto3.client("ec2", region_name=self.region)
        return self._ec2_client

    def _get_ec2_resource(self):
        """Lazy-load boto3 EC2 resource."""
        if self._ec2_resource is None:
            import boto3

            self._ec2_resource = boto3.resource("ec2", region_name=self.region)
        return self._ec2_resource

    @property
    def resource_scope(self) -> str:
        """Cloud-agnostic resource scope (AWS region)."""
        return self.region

    @property
    def ssh_username(self) -> str:
        """Default SSH username for Ubuntu EC2 instances."""
        return "ubuntu"

    def _find_instance_by_name(self, name: str) -> dict | None:
        """Find a running/stopped instance by its Name tag."""
        ec2 = self._get_ec2_client()
        resp = ec2.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [name]},
                {
                    "Name": "instance-state-name",
                    "Values": ["running", "stopped", "pending", "stopping"],
                },
            ]
        )
        for reservation in resp.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                return instance
        return None

    def _find_latest_ubuntu_ami(self, region: str | None = None) -> str:
        """Find the latest Ubuntu 22.04 LTS AMI in the given region."""
        import boto3

        ec2 = boto3.client("ec2", region_name=region or self.region)
        resp = ec2.describe_images(
            Owners=[_UBUNTU_AMI_OWNER],
            Filters=[
                {"Name": "name", "Values": [_UBUNTU_AMI_NAME]},
                {"Name": "architecture", "Values": ["x86_64"]},
                {"Name": "state", "Values": ["available"]},
            ],
        )
        images = sorted(
            resp["Images"], key=lambda x: x["CreationDate"], reverse=True
        )
        if not images:
            raise RuntimeError(
                f"No Ubuntu 22.04 AMI found in {region or self.region}"
            )
        return images[0]["ImageId"]

    def _ensure_vpc_infrastructure(self, region: str | None = None) -> dict:
        """Ensure VPC, subnet, security group, and key pair exist.

        Creates them if they don't exist, using tags for idempotent lookup.

        Returns:
            Dict with keys: subnet_id, security_group_id, key_name.
        """
        import boto3

        ec2 = boto3.client("ec2", region_name=region or self.region)
        ec2_resource = boto3.resource("ec2", region_name=region or self.region)
        tag_name = "waa-pool-infra"

        # Find or create VPC
        vpcs = ec2.describe_vpcs(
            Filters=[{"Name": "tag:Name", "Values": [tag_name]}]
        )["Vpcs"]
        if vpcs:
            vpc_id = vpcs[0]["VpcId"]
        else:
            vpc = ec2_resource.create_vpc(CidrBlock="10.0.0.0/16")
            vpc.create_tags(Tags=[{"Key": "Name", "Value": tag_name}])
            vpc.wait_until_available()
            # Enable DNS
            ec2.modify_vpc_attribute(VpcId=vpc.id, EnableDnsHostnames={"Value": True})
            ec2.modify_vpc_attribute(VpcId=vpc.id, EnableDnsSupport={"Value": True})
            vpc_id = vpc.id

        # Find or create internet gateway
        igws = ec2.describe_internet_gateways(
            Filters=[{"Name": "tag:Name", "Values": [tag_name]}]
        )["InternetGateways"]
        if igws:
            igw_id = igws[0]["InternetGatewayId"]
        else:
            igw = ec2_resource.create_internet_gateway()
            igw.create_tags(Tags=[{"Key": "Name", "Value": tag_name}])
            igw.attach_to_vpc(VpcId=vpc_id)
            igw_id = igw.id

        # Find or create subnet
        subnets = ec2.describe_subnets(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "tag:Name", "Values": [tag_name]},
            ]
        )["Subnets"]
        if subnets:
            subnet_id = subnets[0]["SubnetId"]
        else:
            subnet = ec2_resource.create_subnet(
                VpcId=vpc_id, CidrBlock="10.0.1.0/24"
            )
            subnet.create_tags(Tags=[{"Key": "Name", "Value": tag_name}])
            # Auto-assign public IPs
            ec2.modify_subnet_attribute(
                SubnetId=subnet.id,
                MapPublicIpOnLaunch={"Value": True},
            )
            subnet_id = subnet.id

        # Ensure route table has internet route
        route_tables = ec2.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["RouteTables"]
        for rt in route_tables:
            has_igw_route = any(
                r.get("GatewayId", "").startswith("igw-")
                for r in rt.get("Routes", [])
            )
            if not has_igw_route:
                try:
                    ec2.create_route(
                        RouteTableId=rt["RouteTableId"],
                        DestinationCidrBlock="0.0.0.0/0",
                        GatewayId=igw_id,
                    )
                except Exception:
                    pass  # Route may already exist

        # Find or create security group
        sgs = ec2.describe_security_groups(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "group-name", "Values": [tag_name]},
            ]
        )["SecurityGroups"]
        if sgs:
            sg_id = sgs[0]["GroupId"]
        else:
            sg = ec2_resource.create_security_group(
                GroupName=tag_name,
                Description="WAA pool security group",
                VpcId=vpc_id,
            )
            # TODO: restrict to user's IP (e.g., via https://checkip.amazonaws.com)
            # Open to 0.0.0.0/0 for now; key-based auth mitigates brute-force risk.
            sg.authorize_ingress(
                IpPermissions=[
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 22,
                        "ToPort": 22,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "SSH"}],
                    },
                ]
            )
            sg_id = sg.id

        # Import SSH key pair
        key_name = "waa-pool-key"
        try:
            ec2.describe_key_pairs(KeyNames=[key_name])
        except Exception as e:
            if "InvalidKeyPair.NotFound" not in str(e):
                raise
            ssh_pub_key_path = Path.home() / ".ssh" / "id_rsa.pub"
            if not ssh_pub_key_path.exists():
                raise RuntimeError(
                    f"SSH public key not found at {ssh_pub_key_path}. "
                    "Run: ssh-keygen -t rsa -b 4096"
                )
            ec2.import_key_pair(
                KeyName=key_name,
                PublicKeyMaterial=ssh_pub_key_path.read_bytes(),
            )

        return {
            "subnet_id": subnet_id,
            "security_group_id": sg_id,
            "key_name": key_name,
        }

    # =========================================================================
    # Public API (VMProvider protocol)
    # =========================================================================

    def get_vm_ip(self, name: str) -> Optional[str]:
        """Get EC2 instance public IP address."""
        instance = self._find_instance_by_name(name)
        if instance:
            return instance.get("PublicIpAddress")
        return None

    def get_vm_state(self, name: str) -> Optional[str]:
        """Get EC2 instance state."""
        instance = self._find_instance_by_name(name)
        if instance:
            state = instance["State"]["Name"]
            # Map to Azure-like display status for compatibility
            state_map = {
                "running": "VM running",
                "stopped": "VM deallocated",
                "pending": "VM starting",
                "stopping": "VM stopping",
                "terminated": "VM deleted",
            }
            return state_map.get(state, state)
        return None

    def create_vm(
        self,
        name: str,
        region: str,
        size: str,
        image: str = "",
        admin_username: str = "ubuntu",
        image_id: str | None = None,
    ) -> dict[str, Any]:
        """Create an EC2 instance.

        Args:
            name: Instance name (set as Name tag).
            region: AWS region.
            size: EC2 instance type (e.g., "m5.2xlarge").
            image: Unused (kept for protocol compatibility).
            admin_username: SSH username (default: "ubuntu").
            image_id: AMI ID. If None, uses latest Ubuntu 22.04 LTS.

        Returns:
            Dict with at least "publicIpAddress" key.

        Raises:
            RuntimeError: If instance creation fails.
        """
        import boto3

        # Update manager's region so subsequent operations find this instance
        if region != self.region:
            logger.info(f"Switching region from {self.region} to {region}")
            self.region = region
            self._ec2_client = None
            self._ec2_resource = None

        ec2_client = self._get_ec2_client()
        ec2_resource = self._get_ec2_resource()

        try:
            infra = self._ensure_vpc_infrastructure(region)
            ami_id = image_id or self._find_latest_ubuntu_ami(region)

            # Launch instance
            instances = ec2_resource.create_instances(
                ImageId=ami_id,
                InstanceType=size,
                KeyName=infra["key_name"],
                MinCount=1,
                MaxCount=1,
                NetworkInterfaces=[
                    {
                        "DeviceIndex": 0,
                        "SubnetId": infra["subnet_id"],
                        "Groups": [infra["security_group_id"]],
                        "AssociatePublicIpAddress": True,
                    }
                ],
                BlockDeviceMappings=[
                    {
                        "DeviceName": "/dev/sda1",
                        "Ebs": {
                            "VolumeSize": 128,
                            "VolumeType": "gp3",
                            "DeleteOnTermination": True,
                        },
                    }
                ],
                TagSpecifications=[
                    {
                        "ResourceType": "instance",
                        "Tags": [
                            {"Key": "Name", "Value": name},
                            {"Key": _POOL_TAG_KEY, "Value": "true"},
                        ],
                    }
                ],
            )

            instance = instances[0]
            logger.info(f"Instance {name} ({instance.id}) launching...")

            # Wait for running state
            instance.wait_until_running()
            instance.reload()

            public_ip = instance.public_ip_address
            if not public_ip:
                # Allocate and associate an Elastic IP
                eip = ec2_client.allocate_address(Domain="vpc")
                ec2_client.associate_address(
                    InstanceId=instance.id,
                    AllocationId=eip["AllocationId"],
                )
                ec2_client.create_tags(
                    Resources=[eip["AllocationId"]],
                    Tags=[
                        {"Key": "Name", "Value": f"{name}-eip"},
                        {"Key": _POOL_TAG_KEY, "Value": "true"},
                    ],
                )
                public_ip = eip["PublicIp"]

            logger.info(f"Instance {name} running at {public_ip}")
            return {"publicIpAddress": public_ip, "name": name}

        except Exception as e:
            raise RuntimeError(f"EC2 instance creation failed: {e}") from e

    def delete_vm(self, name: str) -> bool:
        """Terminate EC2 instance and release associated Elastic IP."""
        try:
            instance = self._find_instance_by_name(name)
            if not instance:
                logger.debug(f"Instance {name} not found")
                return True  # Already gone

            instance_id = instance["InstanceId"]
            ec2 = self._get_ec2_client()

            # Find and release any Elastic IPs
            addresses = ec2.describe_addresses(
                Filters=[
                    {"Name": "instance-id", "Values": [instance_id]},
                ]
            ).get("Addresses", [])
            for addr in addresses:
                if addr.get("AssociationId"):
                    ec2.disassociate_address(AssociationId=addr["AssociationId"])
                ec2.release_address(AllocationId=addr["AllocationId"])

            # Terminate instance
            ec2.terminate_instances(InstanceIds=[instance_id])
            logger.info(f"Terminated instance {name} ({instance_id})")
            return True

        except Exception as e:
            logger.error(f"Failed to delete instance {name}: {e}")
            return False

    def deallocate_vm(self, name: str) -> bool:
        """Stop an EC2 instance (equivalent to Azure deallocate)."""
        try:
            instance = self._find_instance_by_name(name)
            if not instance:
                return False

            ec2 = self._get_ec2_client()
            ec2.stop_instances(InstanceIds=[instance["InstanceId"]])
            logger.info(f"Stopping instance {name}")
            return True

        except Exception as e:
            logger.error(f"Failed to stop instance {name}: {e}")
            return False

    def start_vm(self, name: str) -> bool:
        """Start a stopped EC2 instance."""
        try:
            instance = self._find_instance_by_name(name)
            if not instance:
                return False

            ec2 = self._get_ec2_client()
            ec2.start_instances(InstanceIds=[instance["InstanceId"]])
            logger.info(f"Starting instance {name}")

            # Wait for running and get new IP
            waiter = ec2.get_waiter("instance_running")
            waiter.wait(InstanceIds=[instance["InstanceId"]])
            return True

        except Exception as e:
            logger.error(f"Failed to start instance {name}: {e}")
            return False

    def set_auto_shutdown(self, name: str, hours: int = 4) -> bool:
        """Schedule instance shutdown via user-data script.

        v1 implementation: uses `at` or `shutdown` command via SSH.
        A more robust approach would use CloudWatch Events + Lambda.
        """
        try:
            from openadapt_evals.infrastructure.azure_vm import SSH_OPTS, ssh_run

            ip = self.get_vm_ip(name)
            if not ip:
                return False

            minutes = hours * 60
            ssh_run(
                ip,
                f"sudo shutdown -h +{minutes}",
                username=self.ssh_username,
            )
            logger.info(f"Auto-shutdown set for {name} in {hours} hours")
            return True

        except Exception as e:
            logger.warning(f"Failed to set auto-shutdown for {name}: {e}")
            return False

    def find_available_size_and_region(self) -> tuple[str, str, float]:
        """Find a working EC2 instance type and region.

        Checks instance type availability in each region.

        Returns:
            Tuple of (instance_type, region, cost_per_hour).

        Raises:
            RuntimeError: If no available instance type/region found.
        """
        import boto3

        for instance_type, cost in INSTANCE_TYPE_FALLBACKS:
            for region in AWS_REGIONS:
                try:
                    ec2 = boto3.client("ec2", region_name=region)
                    resp = ec2.describe_instance_type_offerings(
                        LocationType="region",
                        Filters=[
                            {"Name": "instance-type", "Values": [instance_type]},
                        ],
                    )
                    if resp.get("InstanceTypeOfferings"):
                        return (instance_type, region, cost)
                except Exception:
                    continue

        raise RuntimeError(
            "No available EC2 instance type/region found. "
            "Check your AWS quotas and region access."
        )

    def list_pool_resources(self, prefix: str = "waa-pool") -> dict[str, list[str]]:
        """List EC2 resources matching a pool prefix.

        Args:
            prefix: Resource name prefix to match.

        Returns:
            Dict with keys "instances" and "eips" mapping to lists of IDs.
        """
        ec2 = self._get_ec2_client()
        result: dict[str, list[str]] = {"instances": [], "eips": []}

        # Find instances by Name tag
        try:
            resp = ec2.describe_instances(
                Filters=[
                    {"Name": "tag:Name", "Values": [f"{prefix}*"]},
                    {
                        "Name": "instance-state-name",
                        "Values": ["running", "stopped", "pending", "stopping"],
                    },
                ]
            )
            for reservation in resp.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    name_tag = ""
                    for tag in instance.get("Tags", []):
                        if tag["Key"] == "Name":
                            name_tag = tag["Value"]
                    result["instances"].append(name_tag or instance["InstanceId"])
        except Exception as e:
            logger.debug(f"Failed to list instances: {e}")

        # Find Elastic IPs with pool tag
        try:
            resp = ec2.describe_addresses(
                Filters=[
                    {"Name": f"tag:{_POOL_TAG_KEY}", "Values": ["true"]},
                ]
            )
            for addr in resp.get("Addresses", []):
                name_tag = ""
                for tag in addr.get("Tags", []):
                    if tag["Key"] == "Name":
                        name_tag = tag["Value"]
                result["eips"].append(name_tag or addr["AllocationId"])
        except Exception as e:
            logger.debug(f"Failed to list EIPs: {e}")

        return result

    def cleanup_pool_resources(
        self, prefix: str, resources: dict[str, list[str]]
    ) -> bool:
        """Delete EC2 pool resources.

        Terminates instances first, then releases Elastic IPs.

        Args:
            prefix: Pool name prefix.
            resources: Dict from list_pool_resources().

        Returns:
            True if all resources were cleaned up.
        """
        ec2 = self._get_ec2_client()
        all_ok = True

        # Terminate instances
        for name in resources.get("instances", []):
            try:
                if name.startswith("i-"):
                    # Raw instance ID (no Name tag) — terminate directly
                    ec2.terminate_instances(InstanceIds=[name])
                    logger.info(f"Terminated {name}")
                else:
                    instance = self._find_instance_by_name(name)
                    if instance:
                        ec2.terminate_instances(InstanceIds=[instance["InstanceId"]])
                        logger.info(f"Terminated {name}")
                    else:
                        logger.warning(f"Instance {name} not found, skipping")
            except Exception as e:
                logger.error(f"Failed to terminate {name}: {e}")
                all_ok = False

        # Release Elastic IPs
        for eip_name in resources.get("eips", []):
            try:
                if eip_name.startswith("eipalloc-"):
                    # Raw allocation ID (no Name tag) — release directly
                    try:
                        ec2.disassociate_address(AllocationId=eip_name)
                    except Exception:
                        pass  # May not be associated
                    ec2.release_address(AllocationId=eip_name)
                else:
                    resp = ec2.describe_addresses(
                        Filters=[{"Name": "tag:Name", "Values": [eip_name]}]
                    )
                    for addr in resp.get("Addresses", []):
                        if addr.get("AssociationId"):
                            ec2.disassociate_address(
                                AssociationId=addr["AssociationId"]
                            )
                        ec2.release_address(AllocationId=addr["AllocationId"])
            except Exception as e:
                logger.error(f"Failed to release EIP {eip_name}: {e}")
                all_ok = False

        return all_ok
