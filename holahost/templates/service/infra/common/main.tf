# ECR repository + lifecycle policy. Applied once, no workspace — shared across all
# environments (frame spec: "infra/common | ECR-репозиторий сервиса с lifecycle-политикой |
# однократно, один на все окружения").
#
# Nothing here is the service's own: the repository name is its `<svc>` name, and the tag
# rules are what makes the platform's build-once/promote-by-digest strategy work at all.

module "ecr" {
  source       = "../../../../infra/modules/service-ecr"
  service_name = "<svc>"
}
