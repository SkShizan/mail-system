import unittest
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import Email
from app.email_sender import process_pending_emails

class TestEmailSender(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch('app.email_sender.smtplib.SMTP')
    def test_send_email_scheduler(self, mock_smtp):
        # Setup mock
        mock_server = MagicMock()
        mock_smtp.return_value = mock_server
        
        # Create a pending email
        email = Email(recipient='test@example.com', subject='Test', body='Hello')
        db.session.add(email)
        db.session.commit()

        # Run scheduler function
        process_pending_emails(self.app)

        # Verify SMTP was called
        mock_smtp.assert_called()
        mock_server.send_message.assert_called()
        
        # Verify email status updated
        updated_email = Email.query.get(email.id)
        self.assertEqual(updated_email.status, 'sent')

if __name__ == '__main__':
    unittest.main()
