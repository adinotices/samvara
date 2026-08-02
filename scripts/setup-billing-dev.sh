#!/bin/bash
# Samvara Billing Development Setup Script
#
# Automates local development environment setup for billing system.
# Includes Stripe test keys, database, and webhook forwarding.
#
# Usage:
#   chmod +x scripts/setup-billing-dev.sh
#   ./scripts/setup-billing-dev.sh
#
# Requirements:
#   - Stripe CLI (install: https://stripe.com/docs/stripe-cli)
#   - Python 3.10+
#   - Node.js 18+
#   - Docker (optional, for Postgres)

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

success() {
    echo -e "${GREEN}✓${NC} $1"
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

error() {
    echo -e "${RED}✗${NC} $1"
    exit 1
}

# Check prerequisites
check_prereqs() {
    info "Checking prerequisites..."

    # Check Python
    if ! command -v python3 &> /dev/null; then
        error "Python 3 is not installed. Please install Python 3.10+"
    fi
    success "Python 3 found"

    # Check Node
    if ! command -v node &> /dev/null; then
        error "Node.js is not installed. Please install Node.js 18+"
    fi
    success "Node.js found"

    # Check Stripe CLI
    if ! command -v stripe &> /dev/null; then
        warn "Stripe CLI not found. Install from: https://stripe.com/docs/stripe-cli"
        read -p "Continue without Stripe CLI? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            error "Stripe CLI is required for local webhook testing"
        fi
    else
        success "Stripe CLI found"
    fi
}

# Setup backend environment
setup_backend() {
    info "Setting up backend environment..."

    cd backend

    # Check if virtual env exists
    if [ ! -d "venv" ]; then
        info "Creating Python virtual environment..."
        python3 -m venv venv
        success "Virtual environment created"
    fi

    # Activate venv
    source venv/bin/activate

    # Install dependencies
    info "Installing Python dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
    success "Python dependencies installed"

    # Create .env file if not exists
    if [ ! -f ".env" ]; then
        info "Creating .env file..."
        cat > .env << 'EOF'
# Stripe Configuration (Test Mode)
STRIPE_SECRET_KEY=sk_test_51234567890abcdefghijklmnop
STRIPE_PUBLISHABLE_KEY=pk_test_1234567890abcdefghijklmnop
STRIPE_WEBHOOK_SECRET=whsec_test_1234567890abcdefghijklmnop

# Database (PostgreSQL)
# For local development with Docker:
#   docker run -d -e POSTGRES_PASSWORD=samvara -p 5432:5432 postgres:15
DATABASE_URL=postgresql://postgres:samvara@localhost:5432/samvara_dev

# Admin API Token (generate random)
ADMIN_API_TOKEN=test_admin_token_dev_only

# Logging
LOG_LEVEL=INFO

# Server
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8081,http://localhost:19000

# Auth Mode (dev = no auth required)
AUTH_MODE=none
EOF
        success ".env file created"
        warn "Update STRIPE_SECRET_KEY and other values from your Stripe Dashboard"
    fi

    cd ..
}

# Setup frontend environment
setup_frontend() {
    info "Setting up frontend environment..."

    cd client

    # Install dependencies
    info "Installing Node dependencies..."
    npm install
    success "Node dependencies installed"

    # Create .env file if not exists
    if [ ! -f ".env" ]; then
        info "Creating .env file..."
        cat > .env << 'EOF'
STRIPE_PUBLISHABLE_KEY=pk_test_1234567890abcdefghijklmnop
API_BASE_URL=http://localhost:8000
EOF
        success ".env file created"
    fi

    cd ..
}

# Setup database
setup_database() {
    info "Setting up database..."

    # Check if running on Docker
    if command -v docker &> /dev/null; then
        info "Docker found. Checking if Postgres container is running..."
        if docker ps | grep -q postgres; then
            success "Postgres container is running"
        else
            info "Starting Postgres container..."
            docker run -d \
                --name samvara-postgres \
                -e POSTGRES_PASSWORD=samvara \
                -e POSTGRES_DB=samvara_dev \
                -p 5432:5432 \
                postgres:15
            success "Postgres container started"

            # Wait for Postgres to be ready
            info "Waiting for Postgres to be ready..."
            sleep 5
        fi
    else
        warn "Docker not found. Ensure Postgres is running on localhost:5432"
    fi

    # Run migrations
    cd backend
    source venv/bin/activate
    info "Running database migrations..."
    alembic upgrade head
    success "Migrations complete"
    cd ..
}

# Setup Stripe webhook forwarding
setup_stripe_webhook() {
    info "Setting up Stripe webhook forwarding..."

    if ! command -v stripe &> /dev/null; then
        warn "Stripe CLI not available, skipping webhook forwarding"
        return
    fi

    # Check if webhook is already running
    if pgrep -f "stripe listen" > /dev/null; then
        success "Stripe webhook forwarding already running"
        return
    fi

    info "Starting Stripe webhook forwarding..."
    info "Note: Run this in a separate terminal:"
    echo ""
    echo "  ${YELLOW}stripe listen --forward-to localhost:8000/v1/billing/webhook/stripe${NC}"
    echo ""
    echo "  Or add to your .env:"
    echo "  STRIPE_WEBHOOK_SECRET=whsec_test_..."
    echo ""
}

# Create test data
create_test_data() {
    info "Creating test data..."

    cd backend
    source venv/bin/activate

    # Create test user
    python3 -c "
from app.db import users, create_engine
from app.config import settings

engine = create_engine(settings.database_url)
with engine.begin() as conn:
    # Insert test user
    conn.execute(
        users.insert().values(
            id='test-user-123',
            email='test@example.com',
            name='Test User',
        )
    )
print('Test user created: test@example.com (ID: test-user-123)')
"

    success "Test data created"
    cd ..
}

# Print setup summary
print_summary() {
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║     Billing Dev Environment Setup Complete ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. ${YELLOW}Update Stripe keys${NC}"
    echo "   • Get test keys from: https://dashboard.stripe.com/test/apikeys"
    echo "   • Update backend/.env: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET"
    echo ""
    echo "2. ${YELLOW}Start local services${NC}"
    echo "   • Backend: cd backend && python -m uvicorn app.main:app --reload"
    echo "   • Frontend: cd client && npm start"
    echo ""
    echo "3. ${YELLOW}Forward Stripe webhooks${NC}"
    echo "   • In a new terminal: stripe listen --forward-to localhost:8000/v1/billing/webhook/stripe"
    echo ""
    echo "4. ${YELLOW}Test the setup${NC}"
    echo "   • Backend tests: cd backend && pytest tests/"
    echo "   • API: curl http://localhost:8000/v1/billing/status"
    echo ""
    echo "5. ${YELLOW}Frontend development${NC}"
    echo "   • Open app in iOS Simulator or Android Emulator"
    echo "   • Navigate to Settings → Payment Method"
    echo ""
    echo "Documentation:"
    echo "   • API Reference: docs/BILLING_API.md"
    echo "   • Deployment: docs/BILLING_DEPLOYMENT.md"
    echo "   • Admin Guide: docs/BILLING_ADMIN_GUIDE.md"
    echo ""
}

# Main setup flow
main() {
    echo -e "${BLUE}╔═══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  Samvara Billing Dev Environment Setup    ║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════╝${NC}"
    echo ""

    check_prereqs
    setup_backend
    setup_frontend
    setup_database
    setup_stripe_webhook
    create_test_data
    print_summary
}

# Run main
main
