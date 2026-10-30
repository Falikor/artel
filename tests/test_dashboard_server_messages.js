'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const root=path.join(__dirname,'..');
function run(language='en') {
  const context={document:{documentElement:{},addEventListener(){}},localStorage:{getItem:()=>language}};
  vm.createContext(context);
  for(const name of ['i18n','server-messages'])vm.runInContext(fs.readFileSync(path.join(root,`office_dashboard/static/js/core/${name}.js`),'utf8'),context);
  return context;
}
test('server UI errors, prompt labels, and feature descriptions are readable in English',()=>{
  const {translateServerMessage:t}=run();
  assert.equal(t('Неизвестный формат памяти'),'Unknown memory format');
  assert.equal(t('Настройки изменены в другой вкладке. Обновите данные перед сохранением.'),'Settings changed in another tab. Refresh the data before saving.');
  assert.equal(t('Тестировщик'),'Tester');
  assert.equal(t('Проверка кандидатов на уроки по коду и тестам.'),'Verifying candidate lessons against code and tests.');
  assert.equal(t('Порядок связанных задач: бэкенд → фронтенд'),'Linked task order: backend → frontend');
  assert.equal(t('Ожидает уточнения в Jira'),'Waiting for clarification in Jira');
});
test('known templates preserve paths, identifiers, limits, and quoted values',()=>{
  const {translateServerMessage:t}=run();
  assert.equal(t('Ассет-пак не найден: /home/пользователь/картинки. Укажите --assets или OFFICE_ASSETS.'),'Asset pack not found: /home/пользователь/картинки. Set --assets or OFFICE_ASSETS.');
  assert.equal(t('В /tmp/assets не найден набор анимаций 06_CHARACTER_ANIMATIONS* (characters/<id>/atlas.png + animations.json).'),'No 06_CHARACTER_ANIMATIONS* animation set found in /tmp/assets (characters/<id>/atlas.png + animations.json).');
  assert.equal(t('generation: нужен текст до 6000 символов без управляющих символов'),'generation: enter up to 6000 characters without control characters');
  assert.equal(t('в конфиге неизвестный персонаж «неизвестный»'),'Unknown character in the configuration: “неизвестный”');
  assert.equal(t('Не удалось прочитать хранилище: PermissionError'),'Could not read the memory store: PermissionError');
  assert.equal(t('цена input — не число'),'The input price is not a number');
});
test('unknown messages, arbitrary text, and near-matches are not rewritten',()=>{
  const {translateServerMessage:t}=run();
  for(const text of ['Корпус 1','Офис тестирования','Система: Неизвестный формат памяти','Запись не найдена\nМой текст','generation: нужен текст до 6000 символов без управляющих символов\nдополнение','цена пользователь — не число','Текст задания от пользователя','Не удалось прочитать хранилище: ValueError\n'])assert.equal(t(text),text);
});
test('Russian messages and identifiers are returned unchanged in Russian mode',()=>{
  const {translateServerMessage:t}=run('ru');
  for(const text of ['Тестировщик','generation: нужен текст до 6000 символов без управляющих символов','Нет такого текста',null,23])assert.equal(t(text),text);
});
test('catalog covers all actual backend profile and stage labels without translating prompt bodies',()=>{
  const context=run(),source=fs.readFileSync(path.join(root,'jira_gigacode/prompt_control.py'),'utf8');
  const labels=[...source.matchAll(/'(?:label|description)': '([^']+)'/g)].map(m=>m[1]);
  assert.equal(labels.length,20);
  for(const label of labels)assert.doesNotMatch(context.translateServerMessage(label),/[А-Яа-яЁё]/,label);
  const body=source.match(/'instructions': '(Твоя специализация[^']+)'/)[1];
  assert.equal(context.translateServerMessage(body),body);
});
test('template registration rejects partial or stateful patterns',()=>{
  const context=run();
  assert.throws(()=>context.registerServerMessagePatterns([{match:/part/,translate:()=>''}]),/complete message/);
  assert.throws(()=>context.registerServerMessagePatterns([{match:/^part$/g,translate:()=>''}]),/complete message/);
  assert.throws(()=>context.registerServerMessagePatterns([{match:/^part$/y,translate:()=>''}]),/complete message/);
});
