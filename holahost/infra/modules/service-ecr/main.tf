# The image repository every Holahost service gets, and the tag rules that make
# build-once/promote-by-digest trustworthy. Called from a service's `infra/common` root,
# which is applied once for all environments.

resource "aws_ecr_repository" "this" {
  name                 = var.service_name
  image_tag_mutability = "IMMUTABLE_WITH_EXCLUSION"

  # `git-<sha>` and `release-v*` are immutable so the digest a tag names stays stable for
  # build-once/promote-by-digest; `latest*` stays mutable for a bootstrap push before the
  # first real deploy exists.
  #
  # Immutability is what makes both tags mean anything, so nothing in a pipeline may write
  # either twice: `git-<sha>` is written once per commit by deploy-staging (which reuses
  # the existing digest instead of rebuilding when the tag is already there), and
  # `release-v*` once per version by promote-prod, after the prod deploy answers its smoke
  # check — never at build time, where a release branch's later stabilisation commits would
  # each collide with the first one's tag.
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
        description  = "Keep last ${var.keep_sha_images} git-<sha> images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["git-"]
          countType     = "imageCountMoreThan"
          countNumber   = var.keep_sha_images
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep last ${var.keep_untagged_images} untagged images"
        selection = {
          tagStatus   = "untagged"
          countType   = "imageCountMoreThan"
          countNumber = var.keep_untagged_images
        }
        action = { type = "expire" }
      },
    ]
  })
}
