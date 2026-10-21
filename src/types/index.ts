export type LeadStatus = 'draft' | 'sent' | 'replied' | 'no_response' | 'won' | 'lost';
export type MessageType = 'initial' | 'follow_up';

export interface Lead {
  id: string;
  profile_id: string | null;
  business_name: string;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  business_type: string;
  context_notes: string | null;
  status: LeadStatus;
  created_at: string;
  last_contacted_at: string | null;
  follow_up_due_at: string | null;
  contact_method: 'email' | 'phone';
}

export interface Message {
  id: string;
  lead_id: string;
  generated_text: string;
  final_text: string | null;
  sent_at: string | null;
  message_type: MessageType;
  created_at: string;
}

export interface Profile {
  id: string;
  name: string;
  sender_name: string;
  sender_email: string;
  sender_phone: string | null;
  contact_person: string | null;
  email_template: string | null;
  created_at: string;
}
