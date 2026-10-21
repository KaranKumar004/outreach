-- 1. Make the email column nullable in the leads table
ALTER TABLE leads ALTER COLUMN email DROP NOT NULL;

-- 2. Add contact_method field to the leads table
ALTER TABLE leads ADD COLUMN IF NOT EXISTS contact_method TEXT DEFAULT 'email';

-- 3. Populate contact_method based on existing email/phone data
UPDATE leads SET contact_method = 'email' WHERE email IS NOT NULL AND email NOT LIKE 'no-email%';
UPDATE leads SET contact_method = 'phone' WHERE email IS NULL OR email LIKE 'no-email%';

-- 4. Clean up the old 'no-email' placeholder emails by setting them to NULL
UPDATE leads SET email = NULL WHERE email LIKE 'no-email%';
