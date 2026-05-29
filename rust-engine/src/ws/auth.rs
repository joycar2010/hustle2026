use jsonwebtoken::{decode, DecodingKey, Validation, Algorithm};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct Claims {
    pub sub: String,
}

pub fn validate_token(token: &str, secret: &str) -> Result<String, String> {
    let key = DecodingKey::from_secret(secret.as_bytes());
    let mut validation = Validation::new(Algorithm::HS256);
    validation.validate_exp = false;
    validation.required_spec_claims.clear();
    match decode::<Claims>(token, &key, &validation) {
        Ok(data) => Ok(data.claims.sub),
        Err(e) => Err(format!("JWT validation failed: {e}")),
    }
}
