from django.urls import path

from .views import (
    CheckEligibilityView,
    CreateLoanView,
    CustomerLoansView,
    LoanDetailView,
    RegisterView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("check-eligibility/", CheckEligibilityView.as_view(), name="check-eligibility"),
    path("create-loan/", CreateLoanView.as_view(), name="create-loan"),
    path("view-loan/<int:loan_id>/", LoanDetailView.as_view(), name="view-loan"),
    path("view-loans/<int:customer_id>/", CustomerLoansView.as_view(), name="view-loans"),
]
