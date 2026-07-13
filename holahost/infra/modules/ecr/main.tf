resource "aws_ecr_repository" "api" {
  name                 = var.repository_name
  image_tag_mutability = "IMMUTABLE_WITH_EXCLUSION"

  # git-<sha> / release-v* are immutable → digest↔sha is stable for build-and-promote (§13.5);
  # `latest` stays mutable so a bootstrap image can be re-pushed before the first Lambda apply.
  image_tag_mutability_exclusion_filter {
    filter      = "latest*"
    filter_type = "WILDCARD"
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Keep last 50 git-<sha> + last 30 untagged; release-v* match no rule → retained (§13.5).
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name

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
