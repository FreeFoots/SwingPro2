"""Create an administrator without a bundled account or password."""
import argparse
from getpass import getpass
from passlib.hash import bcrypt
from app.core.deps import SessionLocal
from app.db.models.user import User, RoleEnum
from app.services.auth import validate_password_strength


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--telephone', required=True, help='Your own 11 digit account number')
    parser.add_argument('--username', default='管理员')
    args = parser.parse_args()
    if not args.telephone.isascii() or not args.telephone.isdigit() or len(args.telephone) != 11:
        parser.error('Telephone must contain 11 digits')
    password = getpass('New administrator password: ')
    if not validate_password_strength(password):
        parser.error('Password must be 8–16 alphanumeric characters, including a letter and a digit')
    if password != getpass('Confirm password: '):
        parser.error('Passwords do not match')
    with SessionLocal() as db:
        if db.query(User).filter(User.telephone == args.telephone).first():
            parser.error('Account already exists; no changes were made')
        db.add(User(telephone=args.telephone, username=args.username, password=bcrypt.hash(password),
                    role=RoleEnum.super_admin, membership_tier=None, status=True))
        db.commit()
    print('Administrator created.')


if __name__ == '__main__':
    main()
