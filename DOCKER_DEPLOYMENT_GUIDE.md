# CaseHarvester ECS Worker Deployment Guide

## Status: Infrastructure Ready, Docker Build Pending

### What's Been Created ✅

1. **SQS Queues** (3 queues for job processing)
   - `caseharvester-spider-queue` - For spider jobs
   - `caseharvester-scraper-queue` - For scraper jobs
   - `caseharvester-parser-queue` - For parser jobs

2. **IAM Roles**
   - `ecsTaskExecutionRole` - Allows ECS to pull images and write logs
   - `caseharvester-lambda-parser-role` - Task role with S3, SQS, RDS access

3. **ECR Repository**
   - Repository: `767398110838.dkr.ecr.us-east-1.amazonaws.com/caseharvester-worker`
   - Status: Created, ready for image push

4. **Files Created**
   - `Dockerfile.worker` - Docker image definition
   - `task-definition.json` - ECS task configuration

---

## Next Steps: Build and Deploy Docker Image

### Prerequisites

**Install Docker Desktop** (Required)
- Download: https://www.docker.com/products/docker-desktop/
- After installation, ensure Docker is running

### Step 1: Build Docker Image

```bash
cd /Users/jei/Downloads/CaseHarvester-develop

# Verify Docker is running
docker --version

# Build the worker image (takes 5-10 minutes)
docker build -f Dockerfile.worker -t caseharvester-worker .
```

### Step 2: Authenticate with ECR

```bash
# Get ECR login token
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  767398110838.dkr.ecr.us-east-1.amazonaws.com
```

### Step 3: Tag and Push Image

```bash
# Tag the image
docker tag caseharvester-worker:latest \
  767398110838.dkr.ecr.us-east-1.amazonaws.com/caseharvester-worker:latest

# Push to ECR (takes 5-10 minutes)
docker push 767398110838.dkr.ecr.us-east-1.amazonaws.com/caseharvester-worker:latest
```

### Step 4: Create CloudWatch Log Group

```bash
aws logs create-log-group \
  --log-group-name /ecs/caseharvester-worker \
  --region us-east-1
```

### Step 5: Register Task Definition

```bash
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json
```

### Step 6: Deploy ECS Service

```bash
# Get cluster ARN
CLUSTER_ARN=$(aws cloudformation describe-stacks \
  --stack-name caseharvester-static-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterArn`].OutputValue' \
  --output text \
  --region us-east-1)

# Get subnets
SUBNET1=$(aws cloudformation describe-stacks \
  --stack-name caseharvester-static-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`VPCPublicSubnet1Id`].OutputValue' \
  --output text \
  --region us-east-1)

SUBNET2=$(aws cloudformation describe-stacks \
  --stack-name caseharvester-static-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`VPCPublicSubnet2Id`].OutputValue' \
  --output text \
  --region us-east-1)

# Get security group
SG=$(aws cloudformation describe-stacks \
  --stack-name caseharvester-static-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`VPCDefaultSecurityGroupId`].OutputValue' \
  --output text \
  --region us-east-1)

# Create ECS service with 3 workers
aws ecs create-service \
  --cluster $CLUSTER_ARN \
  --service-name caseharvester-spider-worker \
  --task-definition caseharvester-spider-worker \
  --desired-count 3 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET1,$SUBNET2],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --region us-east-1
```

---

## How It Works

### Architecture

```
User adds jobs to SQS queue
          ↓
ECS Workers (3 instances) poll queue
          ↓
Process case numbers (spider)
          ↓
Download HTML (scraper)
          ↓
Upload to S3 → Triggers Lambda parser
          ↓
Data stored in PostgreSQL
```

### Adding Jobs to Queue

#### Spider Jobs (Find Case Numbers)
```bash
aws sqs send-message \
  --queue-url https://sqs.us-east-1.amazonaws.com/767398110838/caseharvester-spider-queue \
  --message-body '{
    "court": "BALTIMORE CITY",
    "site": "CRIMINAL",
    "start_date": "2025-09-01",
    "end_date": "2025-09-30"
  }' \
  --region us-east-1
```

#### Scraper Jobs (Download Case HTML)
```bash
aws sqs send-message \
  --queue-url https://sqs.us-east-1.amazonaws.com/767398110838/caseharvester-scraper-queue \
  --message-body '{"case_number": "CC20250001"}' \
  --region us-east-1
```

---

## Monitoring

### View Worker Logs
```bash
# Stream logs from all workers
aws logs tail /ecs/caseharvester-worker --follow
```

### Check Queue Status
```bash
# Check spider queue
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/767398110838/caseharvester-spider-queue \
  --attribute-names ApproximateNumberOfMessages \
  --region us-east-1

# Check scraper queue
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/767398110838/caseharvester-scraper-queue \
  --attribute-names ApproximateNumberOfMessages \
  --region us-east-1
```

### Check Running Tasks
```bash
aws ecs list-tasks \
  --cluster $CLUSTER_ARN \
  --service-name caseharvester-spider-worker \
  --region us-east-1
```

### Check Database for Results
```bash
export PGPASSWORD="MD_Court_Secure_2025!"

psql -h mjcs-dev.c6r2wkokq7rk.us-east-1.rds.amazonaws.com \
     -U caseharvester_admin \
     -d postgres \
     -c "SELECT COUNT(*) FROM cases;"
```

---

## Scaling Workers

### Increase Worker Count
```bash
aws ecs update-service \
  --cluster $CLUSTER_ARN \
  --service caseharvester-spider-worker \
  --desired-count 5 \
  --region us-east-1
```

### Decrease Worker Count
```bash
aws ecs update-service \
  --cluster $CLUSTER_ARN \
  --service caseharvester-spider-worker \
  --desired-count 1 \
  --region us-east-1
```

### Stop All Workers (Save Money)
```bash
aws ecs update-service \
  --cluster $CLUSTER_ARN \
  --service caseharvester-spider-worker \
  --desired-count 0 \
  --region us-east-1
```

---

## Cost Considerations

### ECS Fargate Pricing (us-east-1)
- **vCPU**: $0.04048 per vCPU per hour
- **Memory**: $0.004445 per GB per hour

### Cost Per Worker
- 0.5 vCPU + 1GB Memory = ~$0.025/hour per worker
- 3 workers running 24/7 = ~$54/month

### Recommendations
1. **Start with 1 worker** for testing
2. **Scale up** when processing large batches
3. **Scale to 0** when not actively collecting data
4. **Use spot instances** for 70% cost reduction (not covered in this guide)

---

## Troubleshooting

### Image Build Fails
```bash
# Check Docker is running
docker ps

# View build logs
docker build -f Dockerfile.worker -t caseharvester-worker . --progress=plain
```

### Task Won't Start
```bash
# Check task logs
aws ecs describe-tasks \
  --cluster $CLUSTER_ARN \
  --tasks <task-id> \
  --region us-east-1

# Check CloudWatch logs
aws logs tail /ecs/caseharvester-worker --follow
```

### Workers Not Processing Queue
1. Check queue has messages
2. Check workers are running (`aws ecs list-tasks`)
3. Check CloudWatch logs for errors
4. Verify IAM permissions (SQS, S3, RDS)

---

## Alternative: Run Workers Locally

Instead of ECS, you can run workers on your local machine for testing:

```bash
cd /Users/jei/Downloads/CaseHarvester-develop
source venv/bin/activate

export MJCS_DATABASE_URL="postgresql://caseharvester_admin:MD_Court_Secure_2025!@mjcs-dev.c6r2wkokq7rk.us-east-1.rds.amazonaws.com/postgres"
export CASE_DETAILS_BUCKET="md-caseharvester-html-dev"
export SPIDER_QUEUE_NAME="caseharvester-spider-queue"
export SCRAPER_QUEUE_NAME="caseharvester-scraper-queue"
export PARSER_QUEUE_NAME="caseharvester-parser-queue"
export AWS_DEFAULT_REGION="us-east-1"

# Run spider worker
python3 harvester.py spider --from-queue
```

This is useful for:
- Testing without Docker
- Debugging issues
- One-off data collection

---

## Summary

**Infrastructure Status**: ✅ Ready
**Docker Image**: ⏳ Needs to be built and pushed
**ECS Service**: ⏳ Ready to deploy after image push

**Next Action**: Install Docker Desktop and follow Steps 1-6 above.
