# =============================================================================
# RDS PostgreSQL module
# =============================================================================

# Security group - restrict inbound to VPC CIDR only (no public access)
resource "aws_security_group" "rds" {
  name_prefix = "rds-${var.environment}-"
  vpc_id      = var.vpc_id

  ingress {
    description = "PostgreSQL from application subnets"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "rds-sg-${var.environment}"
    Environment = var.environment
  }
}

# DB subnet group
resource "aws_db_subnet_group" "rds" {
  name       = var.db_subnet_group_name
  subnet_ids = var.db_subnet_ids

  tags = {
    Name        = "${var.db_subnet_group_name}-${var.environment}"
    Environment = var.environment
  }
}

# Parameter group for PostgreSQL
resource "aws_db_parameter_group" "rds" {
  family      = "postgres15"
  name_prefix = "rds-${var.environment}-"

  tags = {
    Name        = "rds-pg-${var.environment}"
    Environment = var.environment
  }
}

# RDS PostgreSQL instance
resource "aws_db_instance" "rds" {
  identifier = "rds-${var.environment}-primary"

  engine            = "postgres"
  engine_version    = "15.5"
  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage
  storage_encrypted = var.db_encrypted

  db_name  = "appdb"
  username = var.db_username
  password = var.db_password

  # Security requirements
  publicly_accessible     = false
  deletion_protection     = true
  backup_retention_period = var.backup_retention_days
  multi_az                = var.multi_az

  # Network
  db_subnet_group_name   = aws_db_subnet_group.rds.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  # Backups
  backup_window      = "03:00-04:00"
  maintenance_window = "sun:05:00-sun:06:00"

  skip_final_snapshot = true

  # Auto minor version upgrades
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true

  tags = {
    Name        = "rds-${var.environment}-primary"
    Environment = var.environment
  }
}
