from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Customer, Loan
from .serializers import LoanRequestSerializer, RegisterSerializer


def round_to_nearest_lakh(value: Decimal) -> int:
    lakh = Decimal("100000")
    remainder = value % lakh
    if remainder >= lakh / 2:
        value += lakh - remainder
    else:
        value -= remainder
    return int(value)


def calculate_monthly_installment(principal: Decimal, annual_rate: Decimal, tenure: int) -> Decimal:
    principal = Decimal(principal)
    months = Decimal(tenure)
    if months == 0:
        return Decimal("0")
    monthly_rate = Decimal(annual_rate) / Decimal("1200")
    if monthly_rate == 0:
        return principal / months
    factor = (Decimal("1") + monthly_rate) ** months
    return (principal * monthly_rate * factor) / (factor - Decimal("1"))


def get_interest_slab(score: Decimal) -> Decimal | None:
    if score > 50:
        return Decimal("10")
    if score > 30:
        return Decimal("12")
    if score > 10:
        return Decimal("16")
    return None


def compute_credit_score(customer: Customer) -> tuple[Decimal, dict]:
    loans = customer.loans.all()
    today = timezone.now().date()
    active_loans = [loan for loan in loans if loan.is_active]
    total_tenure = sum(loan.tenure for loan in loans)
    total_tenure = total_tenure or 1
    total_emis_on_time = sum(loan.emis_paid_on_time for loan in loans)
    on_time_ratio = Decimal(total_emis_on_time) / Decimal(total_tenure)
    score = Decimal("30")
    score += on_time_ratio * Decimal("40")
    score -= Decimal(len(loans)) * Decimal("1.5")
    current_year_activity = sum(1 for loan in loans if loan.start_date and loan.start_date.year == today.year)
    score += Decimal(current_year_activity) * Decimal("2")
    approved_volume = sum((loan.loan_amount for loan in loans if loan.approved), Decimal("0"))
    score += min(approved_volume / Decimal("100000"), Decimal("20"))
    if score < 0:
        score = Decimal("0")
    if score > 100:
        score = Decimal("100")
    active_amount = sum((loan.loan_amount for loan in active_loans), Decimal("0"))
    active_emis = sum((loan.monthly_installment for loan in active_loans), Decimal("0"))
    return score, {"active_amount": active_amount, "active_emis": active_emis}


def evaluate_loan(customer: Customer, loan_amount: Decimal, requested_rate: Decimal, tenure: int) -> dict:
    score, context = compute_credit_score(customer)
    active_amount = context["active_amount"]
    active_emis = context["active_emis"]
    salary = Decimal(customer.monthly_income)
    half_income = salary * Decimal("0.5")
    if active_amount > customer.approved_limit:
        corrected_rate = requested_rate
        monthly_installment = calculate_monthly_installment(loan_amount, corrected_rate, tenure)
        return {
            "approval": False,
            "reason": "Existing loan exposure exceeds approved limit",
            "corrected_rate": corrected_rate,
            "monthly_installment": monthly_installment,
            "score": score,
        }
    if active_emis > half_income:
        corrected_rate = requested_rate
        monthly_installment = calculate_monthly_installment(loan_amount, corrected_rate, tenure)
        return {
            "approval": False,
            "reason": "Current EMIs consume more than 50% of monthly income",
            "corrected_rate": corrected_rate,
            "monthly_installment": monthly_installment,
            "score": score,
        }
    slab = get_interest_slab(score)
    corrected_rate = requested_rate
    if slab and requested_rate < slab:
        corrected_rate = slab
    monthly_installment = calculate_monthly_installment(loan_amount, corrected_rate, tenure)
    if slab is None:
        return {
            "approval": False,
            "reason": "Credit rating too low to approve a loan",
            "corrected_rate": corrected_rate,
            "monthly_installment": monthly_installment,
            "score": score,
        }
    return {
        "approval": True,
        "reason": "Loan approved",
        "corrected_rate": corrected_rate,
        "monthly_installment": monthly_installment,
        "score": score,
    }


class RegisterView(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        approved_limit = round_to_nearest_lakh(Decimal(data["monthly_income"]) * Decimal("36"))
        customer, created = Customer.objects.update_or_create(
            phone_number=data["phone_number"],
            defaults={
                "first_name": data["first_name"],
                "last_name": data["last_name"],
                "age": data["age"],
                "monthly_income": data["monthly_income"],
                "approved_limit": Decimal(approved_limit),
            },
        )
        response_data = {
            "customer_id": customer.id,
            "name": customer.name,
            "age": customer.age,
            "monthly_income": customer.monthly_income,
            "approved_limit": int(customer.approved_limit),
            "phone_number": customer.phone_number,
        }
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(response_data, status=status_code)


class CheckEligibilityView(APIView):
    def post(self, request):
        serializer = LoanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = get_object_or_404(Customer, id=serializer.validated_data["customer_id"])
        loan_amount = Decimal(serializer.validated_data["loan_amount"])
        interest_rate = Decimal(serializer.validated_data["interest_rate"])
        tenure = serializer.validated_data["tenure"]
        evaluation = evaluate_loan(customer, loan_amount, interest_rate, tenure)
        return Response(
            {
                "customer_id": customer.id,
                "approval": evaluation["approval"],
                "interest_rate": float(interest_rate),
                "corrected_interest_rate": float(evaluation["corrected_rate"]),
                "tenure": tenure,
                "monthly_installment": float(evaluation["monthly_installment"]),
            },
            status=status.HTTP_200_OK,
        )


class CreateLoanView(APIView):
    def post(self, request):
        serializer = LoanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = get_object_or_404(Customer, id=serializer.validated_data["customer_id"])
        loan_amount = Decimal(serializer.validated_data["loan_amount"])
        interest_rate = Decimal(serializer.validated_data["interest_rate"])
        tenure = serializer.validated_data["tenure"]
        evaluation = evaluate_loan(customer, loan_amount, interest_rate, tenure)
        if not evaluation["approval"]:
            return Response(
                {
                    "loan_id": None,
                    "customer_id": customer.id,
                    "loan_approved": False,
                    "message": evaluation["reason"],
                    "monthly_installment": float(evaluation["monthly_installment"]),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        start_date = timezone.now().date()
        end_date = start_date + relativedelta(months=tenure)
        loan = Loan.objects.create(
            customer=customer,
            loan_amount=loan_amount,
            tenure=tenure,
            interest_rate=evaluation["corrected_rate"],
            monthly_installment=evaluation["monthly_installment"],
            start_date=start_date,
            end_date=end_date,
            approved=True,
        )
        active_amount = sum((ln.loan_amount for ln in customer.loans.filter(end_date__gte=start_date)), Decimal("0"))
        customer.current_debt = active_amount
        customer.save(update_fields=["current_debt"])
        return Response(
            {
                "loan_id": loan.id,
                "customer_id": customer.id,
                "loan_approved": True,
                "message": "Loan approved",
                "monthly_installment": float(evaluation["monthly_installment"]),
            },
            status=status.HTTP_201_CREATED,
        )


class LoanDetailView(APIView):
    def get(self, request, loan_id):
        loan = get_object_or_404(Loan, id=loan_id)
        return Response(
            {
                "loan_id": loan.id,
                "customer": {
                    "id": loan.customer.id,
                    "first_name": loan.customer.first_name,
                    "last_name": loan.customer.last_name,
                    "phone_number": loan.customer.phone_number,
                    "age": loan.customer.age,
                },
                "loan_amount": float(loan.loan_amount),
                "interest_rate": float(loan.interest_rate),
                "monthly_installment": float(loan.monthly_installment),
                "tenure": loan.tenure,
            }
        )


class CustomerLoansView(APIView):
    def get(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)
        loans = customer.loans.filter(approved=True)
        return Response(
            [
                {
                    "loan_id": loan.id,
                    "customer": {
                        "id": customer.id,
                        "first_name": customer.first_name,
                        "last_name": customer.last_name,
                        "phone_number": customer.phone_number,
                        "age": customer.age,
                    },
                    "loan_amount": float(loan.loan_amount),
                    "interest_rate": float(loan.interest_rate),
                    "monthly_installment": float(loan.monthly_installment),
                    "tenure": loan.tenure,
                }
                for loan in loans
            ]
        )
