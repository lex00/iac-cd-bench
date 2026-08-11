# =============================================================================
# VPC and networking
# =============================================================================

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "vpc-${var.environment}"
    Environment = var.environment
  }
}

# Default SG - restrict all traffic (CKV2_AWS_12)
resource "aws_default_security_group" "main" {
  vpc_id = aws_vpc.main.id

  ingress {
    description = "Allow self traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  egress {
    description = "Allow self traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  tags = {
    Name        = "default-sg-${var.environment}"
    Environment = var.environment
  }
}

# Public subnets (for ALB)
resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = true
  availability_zone       = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name        = "public-${data.aws_availability_zones.available.names[count.index]}-${var.environment}"
    Environment = var.environment
  }
}

# Private subnets (for RDS and EKS)
resource "aws_subnet" "private" {
  count = 2

  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name        = "private-${data.aws_availability_zones.available.names[count.index]}-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name        = "igw-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name        = "public-rt-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

data "aws_availability_zones" "available" {
  state = "available"
}

# =============================================================================
# HTTPS exposure - ALB (dev) / CloudFront (prod)
# =============================================================================

# Application Load Balancer security group
resource "aws_security_group" "alb" {
  name_prefix = "alb-${var.environment}-"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "alb-sg-${var.environment}"
    Environment = var.environment
  }
}

# Target Group for ALB
resource "aws_lb_target_group" "app" {
  name_prefix = "app-${var.environment}-"
  protocol    = "HTTP"
  port        = 80
  vpc_id      = aws_vpc.main.id
  target_type = "instance"

  health_check {
    path                = "/"
    healthy_threshold   = 3
    unhealthy_threshold = 3
  }

  tags = {
    Name        = "tg-${var.environment}"
    Environment = var.environment
  }
}

# ACM certificate (required for HTTPS listener)
resource "aws_acm_certificate" "app" {
  domain_name       = "app.${var.environment}.example.com"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name        = "acm-${var.environment}"
    Environment = var.environment
  }
}

# Application Load Balancer
resource "aws_lb" "app" {
  name               = "alb-${var.environment}"
  internal           = !var.enable_cloudfront
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  drop_invalid_header_fields = true

  tags = {
    Name        = "alb-${var.environment}"
    Environment = var.environment
  }
}

# HTTPS listener (port 443)
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = aws_acm_certificate.app.arn
  ssl_policy        = "ELBSecurityPolicy-TLS-1-2-2017-08"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# CloudFront distribution (prod only)
resource "aws_cloudfront_distribution" "app" {
  count = var.enable_cloudfront ? 1 : 0

  origin {
    domain_name = aws_lb.app.dns_name
    origin_id   = "alb-${var.environment}"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  enabled         = true
  is_ipv6_enabled = true
  comment         = "CloudFront for ${var.environment} canonical app"
  price_class     = "PriceClass_All"

  default_cache_behavior {
    allowed_methods  = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "alb-${var.environment}"

    viewer_protocol_policy = "https-only"
    min_ttl                = 0
    default_ttl            = 3600
    max_ttl                = 86400
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  tags = {
    Name        = "cf-${var.environment}"
    Environment = var.environment
  }
}

# =============================================================================
# S3 replication target bucket (prod only, us-west-2)
# =============================================================================

resource "aws_s3_bucket" "replication_target" {
  count  = var.s3_replication_target_region != "" ? 1 : 0
  bucket = "${var.s3_bucket_name}-replica-${var.s3_replication_target_region}"

  provider = aws.us_west_2

  tags = {
    Name        = "replication-target-${var.environment}"
    Environment = var.environment
    Replication = "target"
  }
}

resource "aws_s3_bucket_versioning" "replication_target" {
  count  = var.s3_replication_target_region != "" ? 1 : 0
  bucket = aws_s3_bucket.replication_target[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "replication_target" {
  count  = var.s3_replication_target_region != "" ? 1 : 0
  bucket = aws_s3_bucket.replication_target[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "replication_target" {
  count  = var.s3_replication_target_region != "" ? 1 : 0
  bucket = aws_s3_bucket.replication_target[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
