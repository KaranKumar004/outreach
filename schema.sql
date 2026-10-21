-- Create custom enum types for lead status and message type
CREATE TYPE lead_status AS ENUM ('draft', 'sent', 'replied', 'no_response', 'won', 'lost');
CREATE TYPE message_type AS ENUM ('initial', 'follow_up');

-- Create leads table
CREATE TABLE IF NOT EXISTS leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_name TEXT NOT NULL,
    contact_name TEXT,
    email TEXT NOT NULL,
    phone TEXT,
    business_type TEXT NOT NULL,
    context_notes TEXT,
    status lead_status NOT NULL DEFAULT 'draft',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_contacted_at TIMESTAMP WITH TIME ZONE,
    follow_up_due_at TIMESTAMP WITH TIME ZONE
);

-- Create messages table
CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    generated_text TEXT NOT NULL,
    final_text TEXT,
    sent_at TIMESTAMP WITH TIME ZONE,
    message_type message_type NOT NULL DEFAULT 'initial',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Add index on lead_id for performance
CREATE INDEX IF NOT EXISTS idx_messages_lead_id ON messages(lead_id);
-- Add index on lead status
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
