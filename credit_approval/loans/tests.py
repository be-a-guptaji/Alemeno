from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import Customer, Loan


class LoanAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = Customer.objects.create(
            first_name="Ada",
            last_name="Lovelace",
            phone_number="9000000000",
            age=30,
            monthly_income=50000,
            approved_limit=Decimal("2000000"),
            current_debt=Decimal("0"),
        )
        Loan.objects.create(
            customer=self.customer,
            loan_amount=Decimal("500000"),
            tenure=12,
            interest_rate=Decimal("12"),
            monthly_installment=Decimal("15000"),
            emis_paid_on_time=12,
            start_date=timezone.now().date() - relativedelta(months=3),
            end_date=timezone.now().date() + relativedelta(months=9),
            approved=True,
        )

    def test_register_sets_limit_rounding(self):
        payload = {
            "first_name": "Grace",
            "last_name": "Hopper",
            "age": 25,
            "monthly_income": 55000,
            "phone_number": "9123456789",
        }
        response = self.client.post(reverse("register"), payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        self.assertEqual(data["approved_limit"], 2000000)
        self.assertEqual(data["phone_number"], payload["phone_number"])

    def test_check_eligibility_corrects_interest(self):
        payload = {
            "customer_id": self.customer.id,
            "loan_amount": Decimal("300000"),
            "interest_rate": Decimal("8.00"),
            "tenure": 24,
        }
        response = self.client.post(reverse("check-eligibility"), payload, format="json")
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        self.assertTrue(data["approval"])
        self.assertEqual(data["corrected_interest_rate"], 10.0)
        self.assertGreater(data["monthly_installment"], 0)

    def test_create_loan_denied_when_emis_exceed_half_salary(self):
        Loan.objects.create(
            customer=self.customer,
            loan_amount=Decimal("400000"),
            tenure=12,
            interest_rate=Decimal("15"),
            monthly_installment=Decimal("26000"),
            emis_paid_on_time=6,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + relativedelta(months=12),
            approved=True,
        )
        payload = {
            "customer_id": self.customer.id,
            "loan_amount": Decimal("100000"),
            "interest_rate": Decimal("18"),
            "tenure": 6,
        }
        response = self.client.post(reverse("create-loan"), payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        self.assertEqual(
            response.json()["message"],
            "Current EMIs consume more than 50% of monthly income",
        )

    def test_create_and_view_loan_flow(self):
        payload = {
            "customer_id": self.customer.id,
            "loan_amount": Decimal("200000"),
            "interest_rate": Decimal("12"),
            "tenure": 12,
        }
        response = self.client.post(reverse("create-loan"), payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        loan_id = response.json()["loan_id"]
        view_response = self.client.get(reverse("view-loan", args=[loan_id]))
        assert view_response.status_code == status.HTTP_200_OK
        self.assertEqual(view_response.json()["customer"]["id"], self.customer.id)
        list_response = self.client.get(reverse("view-loans", args=[self.customer.id]))
        assert list_response.status_code == status.HTTP_200_OK
        self.assertTrue(len(list_response.json()) >= 1)
