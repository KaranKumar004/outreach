-- 1. Disable Row-Level Security on all tables so they are accessible by the local app API
ALTER TABLE profiles DISABLE ROW LEVEL SECURITY;
ALTER TABLE leads DISABLE ROW LEVEL SECURITY;
ALTER TABLE messages DISABLE ROW LEVEL SECURITY;

-- 2. Insert Default Profile (Karan) if not already present
INSERT INTO profiles (name, sender_name, sender_email, sender_phone, contact_person, email_template)
VALUES (
    'Karan',
    'Karan from Sheetbolt',
    'sheetbolt.analytics@gmail.com',
    '',
    'Karan',
    'Hi {first_name},\n\nI noticed your business {company_name} does not have an automated scheduling system. I can help you build one.\n\nBest, Karan'
) ON CONFLICT (name) DO NOTHING;

-- 3. Insert SKM Dev Team Profile with HTML Template
INSERT INTO profiles (name, sender_name, sender_email, sender_phone, contact_person, email_template)
VALUES (
    'SKM Dev Team',
    'Business Development Team',
    'manojkumar07.sk@gmail.com',
    '+91 98451 36478',
    'Manoj Kumar',
    '<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SKM Enterprises - Outreach Email Draft</title>
</head>
<body style="margin:0; padding:0; background-color:#eef1f5; font-family: Arial, Helvetica, sans-serif;">
<div style="display:none; max-height:0; overflow:hidden; font-size:1px; line-height:1px; color:#eef1f5;">
  Trusted civil contractor for your building''s next project &mdash; 25+ years, 150+ projects completed.
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#eef1f5; padding:24px 0;">
<tr>
<td align="center">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:10px; overflow:hidden; box-shadow:0 2px 10px rgba(0,0,0,0.06);">
    <tr>
      <td bgcolor="#0b1424" style="background-color:#0b1424; padding:26px 32px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td align="left" style="font-family: Arial, Helvetica, sans-serif;">
              <span style="font-size:24px; font-weight:bold; color:#3b82f6; letter-spacing:0.5px;">SK</span>
              <span style="font-size:24px; font-weight:bold; color:#ffffff; letter-spacing:0.5px;"> SKM.</span>
              <span style="font-size:24px; font-weight:bold; color:#f7941d;">.</span>
              <span style="font-size:16px; color:#c9d2e0; letter-spacing:0.5px;"> Enterprises</span>
              <br>
              <span style="font-size:11px; color:#7e8aa3; letter-spacing:1px; text-transform:uppercase;">Civil Work Contractor &nbsp;&bull;&nbsp; Since 2001</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    <tr>
      <td style="padding:36px 32px 8px 32px;">
        <p style="margin:0 0 6px 0; font-size:13px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px; font-weight:bold;">For {{company_name}}</p>
        <h1 style="margin:0 0 16px 0; font-size:22px; line-height:1.35; color:#0b1424;">A trusted contractor for whatever your building needs next.</h1>
        <p style="margin:0 0 16px 0; font-size:15px; line-height:1.6; color:#374151;">
          Hi {{first_name}},
        </p>
        <p style="margin:0 0 16px 0; font-size:15px; line-height:1.6; color:#374151;">
          Buildings always need work eventually &mdash; a renovation, an interior upgrade, structural repairs, or scaffolding for maintenance. When that time comes for {{company_name}}, I''d like SKM Enterprises to be the name you already know.
        </p>
        <p style="margin:0 0 24px 0; font-size:15px; line-height:1.6; color:#374151;">
          We''re a Bengaluru-based civil contracting company with <strong>25+ years</strong> of hands-on experience across residential and commercial projects &mdash; from ground-up construction to renovations, interiors, painting, and scaffolding work.
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding:0 32px 28px 32px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td align="center" style="background-color:#f8fafc; border-radius:8px; padding:16px 6px;" width="25%">
              <div style="font-size:20px; font-weight:bold; color:#0b1424;">25+</div>
              <div style="font-size:11px; color:#64748b; margin-top:2px;">Years Experience</div>
            </td>
            <td width="8"></td>
            <td align="center" style="background-color:#f8fafc; border-radius:8px; padding:16px 6px;" width="25%">
              <div style="font-size:20px; font-weight:bold; color:#0b1424;">150+</div>
              <div style="font-size:11px; color:#64748b; margin-top:2px;">Projects Done</div>
            </td>
            <td width="8"></td>
            <td align="center" style="background-color:#f8fafc; border-radius:8px; padding:16px 6px;" width="25%">
              <div style="font-size:20px; font-weight:bold; color:#0b1424;">76+</div>
              <div style="font-size:11px; color:#64748b; margin-top:2px;">Expert Workers</div>
            </td>
            <td width="8"></td>
            <td align="center" style="background-color:#f8fafc; border-radius:8px; padding:16px 6px;" width="25%">
              <div style="font-size:20px; font-weight:bold; color:#0b1424;">34+</div>
              <div style="font-size:11px; color:#64748b; margin-top:2px;">Machinery Tools</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    <tr><td style="padding:0 32px;"><hr style="border:none; border-top:1px solid #e5e9f0; margin:0;"></td></tr>
    <tr>
      <td style="padding:28px 32px 8px 32px;">
        <p style="margin:0 0 16px 0; font-size:13px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px; font-weight:bold;">What We Handle</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="font-size:14px; color:#374151; padding:6px 0; width:50%;">&#9656; Villas &amp; Multi-Storey Buildings</td>
            <td style="font-size:14px; color:#374151; padding:6px 0; width:50%;">&#9656; Complete Renovations</td>
          </tr>
          <tr>
            <td style="font-size:14px; color:#374151; padding:6px 0;">&#9656; Bespoke Interiors</td>
            <td style="font-size:14px; color:#374151; padding:6px 0;">&#9656; Iron Scaffolding (Fitting &amp; Rent)</td>
          </tr>
          <tr>
            <td style="font-size:14px; color:#374151; padding:6px 0;">&#9656; Painting Work</td>
            <td style="font-size:14px; color:#374151; padding:6px 0;">&#9656; Heavy Machinery on Rent</td>
          </tr>
        </table>
      </td>
    </tr>
    <tr>
      <td align="center" style="padding:28px 32px 8px 32px;">
        <table role="presentation" cellpadding="0" cellspacing="0">
          <tr>
            <td align="center" bgcolor="#3b82f6" style="background-color:#3b82f6; border-radius:6px;">
              <a href="https://skm-enterprises-web.vercel.app/" target="_blank" style="display:inline-block; padding:13px 30px; font-size:14px; font-weight:bold; color:#ffffff; text-decoration:none;">
                View Our Work &amp; Past Projects &rarr;
              </a>
            </td>
          </tr>
        </table>
        <p style="margin:14px 0 0 0; font-size:12px; color:#94a3b8;">
          <a href="https://skm-enterprises-web.vercel.app/" target="_blank" style="color:#3b82f6; text-decoration:none;">skm-enterprises-web.vercel.app</a>
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding:28px 32px 8px 32px;">
        <p style="margin:0 0 4px 0; font-size:14px; line-height:1.6; color:#374151;">
          Happy to arrange a quick site visit or send over a quote &mdash; no pressure either way.
        </p>
        <p style="margin:18px 0 0 0; font-size:14px; line-height:1.5; color:#374151;">
          Best,<br>
          <strong>Business Development Team</strong><br>
          <span style="color:#64748b;">SKM Enterprises</span>
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding:8px 32px 0 32px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f8fafc; border-left:3px solid #3b82f6; border-radius:6px;">
          <tr>
            <td style="padding:14px 18px;">
              <p style="margin:0 0 6px 0; font-size:12px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px; font-weight:bold;">
                This inbox isn''t monitored
              </p>
              <p style="margin:0; font-size:13px; line-height:1.6; color:#374151;">
                For quotes, site visits, or any questions, reach out directly to <strong>Manoj Kumar</strong>:<br>
                &#9742; +91 98451 36478 &nbsp;|&nbsp; &#9993; manojkumar07.sk@gmail.com
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    <tr><td style="padding:24px 32px 0 32px;"><hr style="border:none; border-top:1px solid #e5e9f0; margin:0;"></td></tr>
    <tr>
      <td style="padding:18px 32px 28px 32px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="font-size:12px; color:#94a3b8; line-height:1.7;">
              <strong style="color:#374151;">SKM Enterprises</strong><br>
              No. 19, Sampangi Garden, Opp. to Infant Jesus Church,<br>
              Viveknagar Post, Bangalore - 560047<br><br>
              &#9742; +91 98451 36478 &nbsp;|&nbsp; &#9993; manojkumar07.sk@gmail.com
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</td>
</tr>
</table>
</body>
</html>'
) ON CONFLICT (name) DO NOTHING;

-- 4. Associate any existing leads with default profile
UPDATE leads 
SET profile_id = (SELECT id FROM profiles WHERE name = 'Karan') 
WHERE profile_id IS NULL;
