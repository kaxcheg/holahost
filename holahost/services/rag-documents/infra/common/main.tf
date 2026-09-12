# ECR repository + lifecycle policy for rag-documents. Applied once and shared by every
# environment, which is why it lives here rather than under infra/envs/.
#
# Nothing here is this service's own: the repository name is its `<svc>` name, and the tag
# rules are what makes the platform's build-once/promote-by-digest strategy work at all.

module "ecr" {
  source       = "../../../../infra/modules/service-ecr"
  service_name = "rag-documents"
}
