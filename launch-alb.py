# get clients and resources
import boto3
ec2 = boto3.resource('ec2')
elbv2 = boto3.client('elbv2')
route53 = boto3.client('route53')

# Create the security group for the load balancer
balancer_security_group_name = 'balancer-security-group'
balancer_security_group = ec2.create_security_group(
    GroupName=balancer_security_group_name,
    Description='Security group for the load balancer'
)
response = balancer_security_group.authorize_ingress(
    IpPermissions=[
        {
            'FromPort': 80,
            'ToPort': 80,
            'IpProtocol': 'tcp',
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
        }
    ]
)
print('balancer security group created')

# Create the security group for the instances
instances_security_group_name = 'instances-security-group'
instances_security_group = ec2.create_security_group(
    GroupName=instances_security_group_name,
    Description='Security group for the instances'
)
response = instances_security_group.authorize_ingress(
    IpPermissions=[
        {
            'FromPort': 4567,
            'ToPort': 4567,
            'IpProtocol': 'tcp',
            'UserIdGroupPairs': [
                {
                    'GroupId': balancer_security_group.group_id,
                    'UserId': balancer_security_group.owner_id
                }
            ]
        }
    ]
)
print('instances security group created')

# Create the target group for the application load balancer
response = elbv2.create_target_group(
    Name='alb-target-group',
    Protocol='HTTP',
    Port=4567,
    VpcId=balancer_security_group.vpc_id,
    HealthCheckProtocol='HTTP',
    HealthCheckPort='4567',
    HealthCheckPath='/health',
    HealthCheckIntervalSeconds=10,
    HealthCheckTimeoutSeconds=5,
    HealthyThresholdCount=5,
    UnhealthyThresholdCount=2,
    TargetType='instance'
)
target_group_arn = response['TargetGroups'][0]['TargetGroupArn']
print('target group created')

# We need to get the id of the image we are going to use.
# We will assume that it already exists
image_iterator = ec2.images.filter(
    Filters=[
        {
            'Name': 'name',
            'Values': [
                'java-application-ami'
            ]
        }
    ]
)
image = list(image_iterator)[0]
print('AMI found')

#  Launch the instances
instance_count = 2
instances = ec2.create_instances(
    ImageId=image.image_id,
    InstanceType='t2.micro',
    MaxCount=instance_count,
    MinCount=instance_count,
    SecurityGroups=[
        instances_security_group_name
    ]
)
print('instances launched')

# Add name tags to the instances and create a list of instance ids
# to register the instances with the load balancer.
instance_name = 'java-application'
targets = []
for instance, instance_number in zip(instances, range(instance_count)):

    # Wait for instance to start and reload attributes.
    instance.wait_until_running()
    instance.reload()

    # Add name tag to the instance
    instance.create_tags(
        Tags=[
            {
                'Key': 'Name',
                'Value': instance_name + '-' + str(instance_number)
            }
        ]
    )

    # Add the instance id to the instance id list
    targets.append(
        {
            'Id': instance.instance_id,
            'Port': 4567
        }
    )
print('instances running')

response = elbv2.register_targets(
    TargetGroupArn=target_group_arn,
    Targets=targets
)
print('targets registered')

# Create a list of subnet ids for the load balancer
subnet_iterator = ec2.subnets.filter(
    Filters=[
        {
            'Name': 'vpc-id',
            'Values': [
                balancer_security_group.vpc_id
            ]
        }
    ]
)
subnet_ids = [subnet.subnet_id for subnet in subnet_iterator]

# Create the classic load balancer
load_balancer_name = 'application-load-balancer'
response = elbv2.create_load_balancer(
    Name=load_balancer_name,
    Subnets=subnet_ids,
    SecurityGroups=[
        balancer_security_group.group_id
    ]
)
load_balancer_arn = response['LoadBalancers'][0]['LoadBalancerArn']
print('load balancer created')

# Create a listener
response = elbv2.create_listener(
    LoadBalancerArn=load_balancer_arn,
    Protocol='HTTP',
    Port=80,
    DefaultActions=[
        {
            'Type': 'forward',
            'TargetGroupArn': target_group_arn
        }
    ]
)
print('listener created')

# Get the dns name and zone id for the load balancer
response = elbv2.describe_load_balancers(
    Names=[
        load_balancer_name
    ]
)
load_balancer_description = response['LoadBalancers'][0]
balancer_dns_name = load_balancer_description['DNSName']
balancer_zone_id = load_balancer_description['CanonicalHostedZoneId']

# add the public ip address to route53 so SSH is easier
response = route53.list_hosted_zones_by_name(
    DNSName='doug-nicholson.net'
)
zone_id = response['HostedZones'][0]['Id'][12:]
response = route53.change_resource_record_sets(
    HostedZoneId=zone_id,
    ChangeBatch={
        'Changes': [
            {
                'Action': 'CREATE',
                'ResourceRecordSet': {
                    'Name': 'alb.doug-nicholson.net',
                    'Type': 'A',
                    'AliasTarget': {
                        'HostedZoneId': balancer_zone_id,
                        'DNSName': balancer_dns_name,
                        'EvaluateTargetHealth': False
                    }
                }
            }
        ]
    }
)

# it seems like waiting will be the right thing to do
route53_waiter = route53.get_waiter('resource_record_sets_changed')
route53_waiter.wait(
    Id=response['ChangeInfo']['Id'][8:]
)
print('record for alb.doug-nicholson.net created')

# Success!
print('launch application load balancer script completed')
