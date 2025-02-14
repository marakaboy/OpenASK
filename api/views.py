import email
import os
import json

from django.contrib.auth.models import User, Group
from django.db.models.signals import post_save
from django.template import RequestContext
from django.http import HttpResponse, JsonResponse
from django.dispatch import receiver
from django.conf import settings

from rest_framework import viewsets
from rest_framework import permissions
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework import status
from rest_framework.response import Response as RestReponse

from django_filters.rest_framework import DjangoFilterBackend

from .models import *
from .utils import *
from .serializers import *

from django.db import transaction


class UserViewSet(viewsets.ModelViewSet):
	has_user_field = True
	has_state = True
	filter_backends = [DjangoFilterBackend]
	queryset = User.objects.filter(is_active=True).order_by('-date_joined')
	serializer_class = UserSerializer
	permission_classes = [permissions.IsAdminUser]
	has_user_field = False
	has_state = False
	filterset_fields = ["groups"]

class GroupViewSet(viewsets.ModelViewSet):
	has_user_field = True
	has_state = True
	filter_backends = [DjangoFilterBackend]
	queryset = Group.objects.all()
	serializer_class = group_serializer
	permission_classes = [permissions.IsAdminUser]
	has_user_field = False
	has_state = False

class SondageViewSet(viewsets.ModelViewSet):
	queryset = Sondage.objects.all()
	filter_backends = [DjangoFilterBackend]
	serializer_class = SondageSerializer
	pagination_class = None
	permission_classes = [permissions.IsAuthenticatedOrReadOnly]

	@action(detail=True)
	def result(self, request, pk=None):
		sondage = self.get_object()
		data = {}
		data['sondage'] = SondageSerializer(sondage, context={"request":request}).data
		_questions = []
		for question in Question.objects.filter(sondage=sondage):
			_questions.append({
					"id": question.id, 
					"libelle": question.libelle, 
					"type_response": question.type_response
				})
		_responses = []

		for response in Response.objects.filter(sondage=sondage):
			_response_data = {}
			_response_data['author'] = PersonSerializer(response.person, context={"request":request}).data
			_author_response = []
			for question_response in QuestionResponse.objects.filter(response=response):
				question = question_response.question
				_question_response_data = {"question_libelle":question.libelle, "question_id": question.id}
				if question.type_response == 0:
					_question_response_data['response'] = int(question_response.choice_response)
				elif question.type_response == 1:
					_question_response_data['response'] = json.loads(question_response.choices_response)
				elif question.type_response == 2:
					_question_response_data['response'] = question_response.text_response
				elif question.type_response == 3:
					_question_response_data['response'] = int(question_response.number_response)
				else:
					_question_response_data['response'] = {"status": "Failed to understand this answer"}
				_author_response.append(_question_response_data)

			_response_data['author_response'] = _author_response
			_responses.append(_response_data)



		data['sondage']['questions'] = _questions
		data['sondage']['responses'] = _responses
		return RestReponse(data)
	@action(detail=True)
	def details(self, request, pk=None):
		sondage = self.get_object()
		data = {}
		data['sondage'] = SondageSerializer(sondage, context={"request":request}).data
		_questions = []
		for question in Question.objects.filter(sondage=sondage):
			question_data = {
				"id": question.id, 
				"libelle": question.libelle, 
				"type_response": question.type_response
			}
			if question.type_response == 0 or question.type_response == 1:
				_response_proposal = []
				for response_proposal in ResponseProposal.objects.filter(question=question):
					_response_proposal.append({"libelle":response_proposal.libelle, "id": response_proposal.id})
				question_data['response_proposal'] = _response_proposal
			_questions.append(question_data)


		data['sondage']['questions'] = _questions
		return RestReponse(data)

class QuestionViewSet(viewsets.ModelViewSet):
	filter_backends = [DjangoFilterBackend]
	permission_classes = [permissions.IsAdminUser]
	queryset = Question.objects.all()
	pagination_class = None
	serializer_class = QuestionGetSerializer
	filterset_fields = ["sondage"]

	def list(self, request):
		if "sondage" in request.GET and request.GET['sondage'] != "":
			return super().list(self, request)
		else:
			serializer = self.get_serializer_class()(Question.objects.none(), many=True)
			return RestReponse(serializer.data)

	def get_serializer_class(self):
		if self.request.method == 'POST':
			return QuestionPostSerializer
		else:
			return QuestionGetSerializer

class ResponseProposalViewSet(viewsets.ModelViewSet):
	filter_backends = [DjangoFilterBackend]
	permission_classes = [permissions.IsAuthenticatedOrReadOnly]
	queryset = ResponseProposal.objects.all()
	pagination_class = None
	serializer_class = ResponseProposalGetSerializer
	filterset_fields = ["question"]

	def list(self, request):
		if "question" in request.GET and request.GET['question'] != "":
			return super().list(self, request)
		else:
			return RestReponse(self.get_serializer_class()(ResponseProposal.objects.none(), many=True).data)

	def get_serializer_class(self):
		if self.request.method == 'POST':
			return ResponseProposalPostSerializer
		else:
			return ResponseProposalGetSerializer

class PersonViewSet(viewsets.ModelViewSet):
	filter_backends = [DjangoFilterBackend]
	permission_classes = [permissions.IsAdminUser]
	queryset = Person.objects.all()
	pagination_class = None
	serializer_class = PersonSerializer

	def list(self, request):
		serializer = PersonSerializer(Person.objects.none(), many=True)
		return RestReponse(serializer.data)

class ResponseViewSet(viewsets.ModelViewSet):
	filter_backends = [DjangoFilterBackend]
	permission_classes = [permissions.AllowAny]
	queryset = Response.objects.all()
	pagination_class = None
	serializer_class = ResponseGetSerializer
	filterset_fields = ["sondage"]

	@action(detail=False, methods=['post'])
	def submit(self, request):
		data = request.data

		if "sondage" not in data or data['sondage'] == "":
			return RestReponse({'error':'Sondage id required', 'code': ErrorCode.SONDAGE_ID_MISSING})

		if "person" not in data or data['person'] == None:
			return RestReponse({'error':'Person information required', 'code': ErrorCode.SONDAGE_PERSON_INFORMATION_MISSING})

		if ("email" not in data['person'] or data['person']['email'] == ""):
			if "phone_number" not in data['person'] or data['person']['phone_number'] == "":
				return RestReponse({'error':'Person email address required', 'code': ErrorCode.SONDAGE_PERSON_EMAIL_MISSING})

		if "responses" not in data or data['responses'] == None:
			return RestReponse({'error':'No response submited', 'code': ErrorCode.SONDAGE_RESPONSE_MISSING})

		def safeCheck(data):
			if "first_name" not in data:
				data['first_name'] = ""
			if "last_name" not in data:
				data['last_name'] = ""
			return data

		sondage = Sondage.objects.filter(id=int(data['sondage'])).first()
		if "email" in data['person']:
			if data['person']['email'] != "":
				check_existing_person = Person.objects.filter(email=data['person']['email'])
		elif "phone_number" in data['person']:
			if data['person']['phone_number'] != "":
				check_existing_person = Person.objects.filter(phone_number=data['person']['phone_number'])
		else:
			check_existing_person = Person.objects.filter(email="unknown mail")
			return RestReponse({'error':'No mail and no phone number submitted', 'code': ErrorCode.SONDAGE_NO_MAIL_NO_PHONE_NUMBER})
		isNewPerson = False
		if len(check_existing_person) > 0:
			person = check_existing_person.first()
			if len(Response.objects.filter(person=person)) > 0:
				return RestReponse({'error':'This person already reply to this sondage', 'code': ErrorCode.SONDAGE_PERSON_ALREADY_REPLY})
			else:
				isNewPerson = False
		else:
			person = Person.objects.create(**safeCheck(data['person']))
			isNewPerson = True
		response_obj = Response.objects.create(**{"person":person, "sondage":sondage})

		def resetResponse():
			response_obj.delete()
		
		for response in data['responses']:
			question = Question.objects.filter(id=response)
			if len(question) == 0:
				resetResponse()
				return RestReponse({'error':'Innexistante question; question_id => {}; response => {}'.format(response, data['responses'][response]), 'code': ErrorCode.SONDAGE_QUESTION_NOT_EXIST})
			question = question.first()
			res = data['responses'][response]
			if question.type_response == 0:
				if res == "" or res == None:
					resetResponse()
					return RestReponse({'error':'Bad Response; question_id => {}; response => {}'.format(response, data['responses'][response]), 'code': ErrorCode.SONDAGE_BAD_QUESTION_RESPONSE_TYPE}) 
				try:
					QuestionResponse.objects.create(**{"choice_response": int(res), "question": question, "response": response_obj})
				except Exception as e:
					resetResponse()
					return RestReponse({'error':'Bad Response type; question_id => {}; response => {}; {}'.format(response, data['responses'][response], e), 'code': ErrorCode.SONDAGE_BAD_QUESTION_RESPONSE_TYPE}) 
			elif question.type_response == 1:
				if res == "" or res == None:
					resetResponse()
					return RestReponse({'error':'Bad Response; question_id => {}; response => {}'.format(response, data['responses'][response]), 'code': ErrorCode.SONDAGE_BAD_QUESTION_RESPONSE_TYPE}) 
				try:
					if type(res) == list:
						QuestionResponse.objects.create(**{"choices_response": json.dumps(res), "question": question, "response": response_obj})
					else:
						resetResponse()
						return RestReponse({'error':'Bad Response type; question_id => {}; response => {}; {}'.format(response, data['responses'][response], e), 'code': ErrorCode.SONDAGE_BAD_QUESTION_RESPONSE_TYPE}) 
				except Exception as e:
					resetResponse()
					return RestReponse({'error':'Bad Response type; question_id => {}; response => {}; {}'.format(response, data['responses'][response], e), 'code': ErrorCode.SONDAGE_BAD_QUESTION_RESPONSE_TYPE}) 
			elif question.type_response == 2:
				if res == "" or res == None:
					resetResponse()
					return RestReponse({'error':'Bad Response; question_id => {}; response => {}'.format(response, data['responses'][response]), 'code': ErrorCode.SONDAGE_BAD_QUESTION_RESPONSE_TYPE}) 
				try:
					QuestionResponse.objects.create(**{"text_response": res, "question": question, "response": response_obj})
				except Exception as e:
					resetResponse()
					return RestReponse({'error':'Bad Response type; question_id => {}; response => {}; {}'.format(response, data['responses'][response], e), 'code': ErrorCode.SONDAGE_BAD_QUESTION_RESPONSE_TYPE}) 
			elif question.type_response == 3:
				if res == "" or res == None:
					resetResponse()
					return RestReponse({'error':'Bad Response; question_id => {}; response => {}'.format(response, data['responses'][response]), 'code': ErrorCode.SONDAGE_BAD_QUESTION_RESPONSE_TYPE}) 
				try:
					QuestionResponse.objects.create(**{"number_response": int(res), "question": question, "response": response_obj})
				except Exception as e:
					resetResponse()
					return RestReponse({'error':'Bad Response type; question_id => {}; response => {}; {}'.format(response, data['responses'][response], e), 'code': ErrorCode.SONDAGE_BAD_QUESTION_RESPONSE_TYPE}) 

		return RestReponse({"status": 200})

	def list(self, request):
		if "sondage" in request.GET and request.GET['sondage'] != "":
			return super().list(self, request)
		else:
			serializer = self.get_serializer_class()(Response.objects.none(), many=True)
			return RestReponse(serializer.data)

	def get_serializer_class(self):
		if self.request.method == 'POST':
			return ResponsePostSerializer
		else:
			return ResponseGetSerializer

class QuestionResponseViewSet(viewsets.ModelViewSet):
	filter_backends = [DjangoFilterBackend]
	permission_classes = [permissions.IsAdminUser]
	queryset = QuestionResponse.objects.all()
	pagination_class = None
	serializer_class = QuestionResponseGetSerializer
	filterset_fields = ["question"]

	def list(self, request):
		if "question" in request.GET and request.GET['question'] != "":
			return super().list(self, request)
		else:
			serializer = self.get_serializer_class()(Question.objects.none(), many=True)
			return RestReponse(serializer.data)

	def get_serializer_class(self):
		if self.request.method == 'POST':
			return QuestionResponsePostSerializer
		else:
			return QuestionResponseGetSerializer


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_auth_token(sender, instance=None, created=False, **kwargs):
	if created:
		Token.objects.create(user=instance)