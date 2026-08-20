# ECR repository + lifecycle policy for rag-documents (R-26). Applied once, no workspace — shared
# across all environments (frame spec table: "infra/common | ECR-репозиторий сервиса с
# lifecycle-политикой | однократно, один на все окружения").

resource "aws_ecr_repository" "this" {
  name                 = "rag-documents"
  image_tag_mutability = "IMMUTABLE_WITH_EXCLUSION"

  # git-<sha> / release-v* tags are immutable so digest<->tag stays stable for the
  # build-once/promote-by-digest strategy (R-30/R-31); `latest*` stays mutable for a bootstrap push
  # before the first Lambda-equivalent... i.e. before the first EC2 compose deploy exists.
  image_tag_mutability_exclusion_filter {
    filter      = "latest*"
    filter_type = "WILDCARD"
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 50 git-<sha> images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["git-"]
          countType     = "imageCountMoreThan"
          countNumber   = 50
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep last 30 untagged images"
        selection = {
          tagStatus   = "untagged"
          countType   = "imageCountMoreThan"
          countNumber = 30
        }
        action = { type = "expire" }
      },
    ]
  })
}
