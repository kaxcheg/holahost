resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.name_prefix}-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# OAC for the Lambda Function URL origin — CloudFront signs sigv4 so the Function URL (AWS_IAM) is not
# publicly invocable (D-28).
resource "aws_cloudfront_origin_access_control" "lambda" {
  name                              = "${var.name_prefix}-api-oac"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Security headers for static responses (§10.3). Env-scoped name → one policy per env (identical
# content), keeps the module self-contained (no shared→env cross-state dependency).
resource "aws_cloudfront_response_headers_policy" "security" {
  name = "${var.name_prefix}-security-headers"

  security_headers_config {
    content_security_policy {
      override                = true
      content_security_policy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://api.anthropic.com; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    }
    strict_transport_security {
      override                   = true
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true
    }
    content_type_options {
      override = true
    }
    referrer_policy {
      override        = true
      referrer_policy = "strict-origin-when-cross-origin"
    }
    frame_options {
      override     = true
      frame_option = "DENY"
    }
  }

  # Permissions-Policy is not a first-class field → custom header.
  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
      override = true
    }
  }
}

# Short-TTL cache for /config/* (hot-update schema, §10.6).
resource "aws_cloudfront_cache_policy" "config" {
  name        = "${var.name_prefix}-config-cache"
  min_ttl     = 0
  default_ttl = 300
  max_ttl     = 300

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
  }
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

# /api/lead-capture/* must not be cached and must NOT forward the viewer Host (Function URL SigV4 needs its own
# Host) — managed policies.
data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

# SPA fallback (replaces the global custom_error_response, D-29). Attached to the DEFAULT behavior only
# → /api/lead-capture/* and /config/* (own behaviors) are untouched, so API 4xx are never rewritten. Any request
# without a file extension is a client-side route → serve index.html.
resource "aws_cloudfront_function" "spa_rewrite" {
  name    = "${var.name_prefix}-spa-rewrite"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite extensionless requests to /index.html (default behavior only)."
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      if (!request.uri.includes('.')) {
        request.uri = '/index.html';
      }
      return request;
    }
  EOT
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${var.name_prefix} frontend"
  default_root_object = "index.html"
  aliases             = var.aliases
  price_class         = var.price_class

  # Releases origin: SPA bundle under releases/<git-sha>/ (origin_path).
  origin {
    origin_id                = "s3-releases"
    domain_name              = var.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
    origin_path              = var.release_prefix
  }

  # Config origin: same bucket, no origin_path → serves config/* from the root.
  origin {
    origin_id                = "s3-config"
    domain_name              = var.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # Lambda Function URL origin for /api/lead-capture/* (I-12).
  origin {
    origin_id                = "lambda-api"
    domain_name              = var.api_origin_domain
    origin_access_control_id = aws_cloudfront_origin_access_control.lambda.id

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id           = "s3-releases"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_rewrite.arn
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/config/*"
    target_origin_id           = "s3-config"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.config.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  # API behavior: no caching, forward everything except Host (Function URL SigV4), no static
  # response-headers policy (the Lambda sets its own security headers + CORS, §10.3).
  ordered_cache_behavior {
    path_pattern             = "${var.api_base_url}/*"
    target_origin_id         = "lambda-api"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
  }

  # SPA fallback is handled by aws_cloudfront_function.spa_rewrite (viewer-request, default behavior),
  # not custom_error_response — otherwise a global 403/404→index rewrite would swallow /api/lead-capture/* JSON
  # errors (D-29).

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.acm_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  # CI mutates the releases origin_path per deploy (§13.4) → ignore origin drift (D-15).
  lifecycle {
    ignore_changes = [origin]
  }
}

# Alias A + AAAA per hostname → this distribution.
resource "aws_route53_record" "alias" {
  for_each = {
    for pair in setproduct(var.aliases, ["A", "AAAA"]) :
    "${pair[0]}-${pair[1]}" => { name = pair[0], type = pair[1] }
  }

  zone_id = var.route53_zone_id
  name    = each.value.name
  type    = each.value.type

  alias {
    name                   = aws_cloudfront_distribution.frontend.domain_name
    zone_id                = aws_cloudfront_distribution.frontend.hosted_zone_id
    evaluate_target_health = false
  }
}
