from rest_framework import serializers


class RegisterSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=80)
    last_name = serializers.CharField(max_length=80)
    age = serializers.IntegerField(min_value=0)
    monthly_income = serializers.IntegerField(min_value=0)
    phone_number = serializers.CharField(max_length=15)


class LoanRequestSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField(min_value=1)
    loan_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    interest_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    tenure = serializers.IntegerField(min_value=1)
