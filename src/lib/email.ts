import nodemailer from 'nodemailer';

const smtpHost = process.env.SMTP_HOST;
const smtpPort = process.env.SMTP_PORT ? parseInt(process.env.SMTP_PORT, 10) : 587;
const smtpUser = process.env.SMTP_USER;
const smtpPass = process.env.SMTP_PASS;

export function getTransporter() {
  if (!smtpHost || !smtpUser || !smtpPass) {
    throw new Error(
      'Missing SMTP environment variables. Please configure SMTP_HOST, SMTP_USER, and SMTP_PASS in .env.local.'
    );
  }

  return nodemailer.createTransport({
    host: smtpHost,
    port: smtpPort,
    secure: smtpPort === 465, // true for 465, false for 587
    auth: {
      user: smtpUser,
      pass: smtpPass,
    },
  });
}

interface SendEmailParams {
  to: string;
  subject: string;
  text?: string;
  html?: string;
  senderName?: string;
  replyTo?: string;
}

export async function sendEmail({ to, subject, text, html, senderName, replyTo }: SendEmailParams) {
  const transporter = getTransporter();
  
  const fromName = senderName || "Karan";
  const fromEmail = smtpUser;
  
  const mailOptions: any = {
    from: `"${fromName}" <${fromEmail}>`,
    to,
    subject,
  };

  if (html) {
    mailOptions.html = html;
  } else if (text) {
    mailOptions.text = text;
  }

  if (replyTo) {
    mailOptions.replyTo = replyTo;
  }

  const info = await transporter.sendMail(mailOptions);
  return info;
}
