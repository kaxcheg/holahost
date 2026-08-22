# ECR repository + lifecycle policy for rag-documents (R-26). Applied once, no workspace — shared
# across all environments (frame spec table: "infra/common | ECR-репозиторий сервиса с
# lifecycle-политикой | однократно, один на все окружения").

resource "aws_ecr_repository" "this" {
  name                 = "rag-documents"
  image_tag_mutability = "IMMUTABLE_WITH_EXCLUSION"

  # git-<sha> / release-v* tags are immutable so digest<->tag stays stable for the
  # build-once/promote-by-digest strategy (R-30/R-31); `latest*` stays mutable for a bootstrap push
  # before the first Lambda-equivalent... i.e. before the first EC2 compose deploy exists.
  #
  # Immutability is what makes both tags trustworthy, so nothing in the pipeline may ever write
  # either one twice: `git-<sha>` is written once per commit by deploy-staging (which reuses the
  # existing digest instead of rebuilding if the tag is already there), and `release-v*` is written
  # once per version by promote-prod, after the prod deploy answers its smoke check — never at
  # build time, where a release branch's later stabilization commits would each collide with the
  # first one's tag.
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
