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

variable "sample_guidebook_key" {
  type        = string
  description = "S3 object key for the published sample guidebook (config.yaml sample_guidebook_key) — also injected by lambda as SAMPLE_GUIDEBOOK_S3_KEY (single source, no drift)."
}

variable "system_prompt_objects" {
  type        = map(object({ key = string, source = string }))
  description = "Per-env system-prompt objects (env => {key, source}), from config.yaml envs.<env>.system_prompt_key / system_prompt_path. One aws_s3_object published per entry."
}
