import boto3
ec2 = boto3.resource('ec2')
elbv2 = boto3.client('elbv2')
route53 = boto3.client('route53')

# add the public ip address to route53 so SSH is easier
response = route53.list_hosted_zones_by_name(
    DNSName='doug-nicholson.net'
)
local_zone_id = response['HostedZones'][0]['Id'][12:]
dns_name='alb.doug-nicholson.net'
response = route53.list_resource_record_sets(
    HostedZoneId=local_zone_id,
    StartRecordName=dns_name,
    StartRecordType='A',
    MaxItems='1'
)
for record_set in response['ResourceRecordSets']:
    if record_set['Name'] == dns_name + '.':
        response = route53.change_resource_record_sets(
            HostedZoneId=local_zone_id,
            ChangeBatch={
                'Changes': [
                    {
                        'Action': 'DELETE',
                        'ResourceRecordSet': record_set
                    }
                ]
            }
        )
        # it seems like waiting will be the right thing to do
        route53_waiter = route53.get_waiter('resource_record_sets_changed')
        route53_waiter.wait(
            Id=response['ChangeInfo']['Id'][8:]
        )
        print('record for alb.doug-nicholson.net deleted')

# Delete the application load balancer
try:
    response = elbv2.describe_load_balancers(
        Names=[
            'application-load-balancer'
        ]
    )
except:
    pass
else:
    load_balancer_arn = response['LoadBalancers'][0]['LoadBalancerArn']
    response = elbv2.delete_load_balancer(
        LoadBalancerArn=load_balancer_arn
    )
    print('load balancer deleted')
balancer_security_group_name='balancer-security-group'

# Delete the instances
instances_security_group_name = 'instances-security-group'
instance_iterator = ec2.instances.filter(
    Filters=[
        {
            'Name': 'instance.group-name',
            'Values': [
                instances_security_group_name
            ]
        }
    ]
)
for instance in instance_iterator:
    response = instance.terminate()
for instance in instance_iterator:
    instance.wait_until_terminated()
print('instances terminated')

# Delete target group
try:
    response = elbv2.describe_target_groups(
        Names=[
            'alb-target-group'
        ]
    )
except:
    pass
else:
    target_group_arn = response['TargetGroups'][0]['TargetGroupArn']
    response = elbv2.delete_target_group(
        TargetGroupArn=target_group_arn
    )
    print('target group deleted')

# Delete the security group, we have to do our own filtering, and
for security_group in [instances_security_group_name, balancer_security_group_name]:
    security_group_iterator = ec2.security_groups.filter(
        Filters=[
            {
                'Name': 'group-name',
                'Values': [
                    security_group
                ]
            }
        ]
    )
    for security_group in security_group_iterator:
        response = security_group.delete()
print('security groups deleted')

# Success!
print('cleanup application load balancer script completed')
