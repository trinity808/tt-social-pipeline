from review.emailer import send_email


send_email(
    subject="[TEST] Trinity Tree Social Review",
    text_body=(
        "This is a test of the Trinity Tree "
        "social review email system."
    ),
    html_body="""
    <html>
        <body>
            <h2>Trinity Tree Social Review</h2>

            <p>
                This is a test of the human-review
                email notification system.
            </p>

            <p>
                If you received this, SMTP,
                Secret Manager, and recipient
                configuration are working.
            </p>
        </body>
    </html>
    """,
)

print("Test email sent.")