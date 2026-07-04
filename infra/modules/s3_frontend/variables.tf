variable "bucket_name" {
  type        = string
  description = "Frontend bucket name (supplied from infra/config.yaml). Single bucket shared by staging + prod CloudFront (§13.4/§13.5); globally unique."
}

variable "guidebook_template_path" {
  type        = string
  description = "Path to the guidebook template JSON published as config/template_schema.json — value from infra/config.yaml, resolved to the repo root by the caller."
}

variable "sample_guidebook_path" {
  type        = string
  description = "Path to the sample guidebook markdown published as config/sample_guidebook.md — value from infra/config.yaml, resolved to the repo root by the caller."
}
