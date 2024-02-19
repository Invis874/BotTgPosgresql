import telebot
from telebot import types

from sql_app import models
from sql_app.database import Session, engine

import config

bot = telebot.TeleBot(config.TOKEN)

models.Base.metadata.create_all(bind=engine)
Departments = models.Departments
Group = models.Group
Contingent = models.Contingent


@bot.message_handler(content_types=['text'])
def start(message):
	#Выбор между Записью и Выпиской
	if message.text == '/start':
		keyboard = types.InlineKeyboardMarkup() #наша клавиатура

		key_tk = types.InlineKeyboardButton(text="Узнать", callback_data="to_know")
		keyboard.add(key_tk)
		key_r = types.InlineKeyboardButton(text="Записать", callback_data="record")
		keyboard.add(key_r)
		
		bot.send_message(message.from_user.id, "Вы хотите узнать или записать", reply_markup=keyboard) #Грубо говоря мы принемаем исходные данные

	else:
		bot.send_message(message.from_user.id, 'Напиши /start') #пока не напишут "/start"

def record(message):
	x = message.text
	x = x.split()


	session = Session()
	contingent = Contingent(id_groups=group, number_of_students=x[1],
                                 date=x[0])
	session.add(contingent) #Записываем новые данные в БД
	session.commit()
	bot.send_message(call.message.chat.id, 'Записано :)')

def conclusion_doc(message):
	session = Session()
	cont_text = []
	for i in session.query(Contingent).filter(Contingent.id_groups == group):
		cont_text.append(f"Дата документа: {i.date}, число учащихся: {i.number_of_students}")
	session.commit()
	print(cont_text)
	bot.send_message(message.from_user.id, 'Движение контингентов данной группы: \n' + '\n'.join(cont_text))


@bot.callback_query_handler(func=lambda call: True)
def callback_worker(call):
	#Вы хотите узнать или записать
	global branch
	global flag
	if call.data == "to_know": 
		flag = False
		session = Session()

		keyboard = types.InlineKeyboardMarkup() #наша клавиатура
		#Вывод всех отдилений
		for i in session.query(Departments).all():
			key = types.InlineKeyboardButton(text=i.name, callback_data=f"branch {i.id}") #Наименование отдиления
			keyboard.add(key)

		session.commit() #Выход из сеанса

		bot.edit_message_text('Выбирите отдиление', reply_markup=keyboard, chat_id=call.message.chat.id, message_id=call.message.message_id) #Текст над клавиатурой #Переход на выборку отделений для того чтоб выбрать существующею информацию

	elif call.data == "record":
		flag = True
		session = Session()

		keyboard = types.InlineKeyboardMarkup() #наша клавиатура
		#Вывод всех отдилений
		for i in session.query(Departments).all():
			key = types.InlineKeyboardButton(text=i.name, callback_data=f"branch {i.id}") #Наименование отдиления
			keyboard.add(key)

		session.commit() #Выход из сеанса

		bot.edit_message_text('Выбирите отдиление', reply_markup=keyboard, chat_id=call.message.chat.id, message_id=call.message.message_id) #Текст над клавиатурой #Переход на выборку отделений для того чтоб выбрать существующею информацию

    #Выбирите отдиление
	elif call.data.split()[0] == "branch":
		branch = call.data.split()[1]
		print(branch)
		#Запуск с сеанса с БД
		session = Session()

		keyboard = types.InlineKeyboardMarkup() #наша клавиатура
		for i in session.query(Group).filter(Group.id_departments == branch):

			key = types.InlineKeyboardButton(text=i.cipher, callback_data=i.id) #ТУТ Я ОСТАНОВИЛСЯ
			keyboard.add(key)

		session.commit()

		bot.edit_message_text('Выбирите группу', reply_markup=keyboard, chat_id=call.message.chat.id, message_id=call.message.message_id)

	#Выбирите группу
	else:
		global group
		group = call.data
		print(group)
		message = call.message
		if flag:
			bot.edit_message_text('Запишите дату и количество контингентов в виде: \"дд.мм.гг n\"', chat_id=call.message.chat.id, message_id=call.message.message_id)
			bot.register_next_step_handler(message, record) #Переход на запись данных
		else:
			session = Session()
			cont_text = []
			for i in session.query(Contingent).filter(Contingent.id_groups == group):
				cont_text.append(f"Дата документа: {i.date}, число учащихся: {i.number_of_students}")
			session.commit()
			print(cont_text)
			bot.edit_message_text('Движение контингентов данной группы: \n' + '\n'.join(cont_text), chat_id=call.message.chat.id, message_id=call.message.message_id)


#Бот задает серверу вопрос писал ли ему кто то
bot.polling(none_stop=True, interval=0)