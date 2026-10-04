/**
 * Simple CRM – client information form.
 *
 * Paste this into your CRM Google Sheet (Extensions → Apps Script), then run createClientForm once.
 * It creates a Google Form for clients, and every submission is added to the Customers tab in the
 * same columns the Simple CRM app uses. The app gives each new row a Customer ID the next time it loads.
 */

// Form question title → Customers column. Change the titles freely; keep the column names as they are.
const QUESTIONS = [
  { title: 'First name',     column: 'First Name' },
  { title: 'Middle name',    column: 'Middle Name' },
  { title: 'Last name',      column: 'Last Name' },
  { title: 'Phone number',   column: 'Phone' },
  { title: 'Email address',  column: 'Email', email: true },
  { title: 'Street address', column: 'Address Line 1', help: 'e.g. 123 Main St' },
  { title: 'Apt, suite or unit', column: 'Address Line 2' },
  { title: 'City',           column: 'City' },
  { title: 'State',          column: 'State', help: 'e.g. MD' },
  { title: 'ZIP code',       column: 'ZIP', zip: true },
  { title: 'Anything else you would like us to know?', column: 'Notes', paragraph: true },
];

const FORM_TITLE = 'Client Information';
const FORM_DESCRIPTION =
  'Please share your contact details so we can keep in touch. ' +
  'Every question is optional: fill in whatever you are comfortable sharing.';
const CUSTOMERS_TAB = 'Customers';

/** Run this once. It creates the form and connects it to this sheet. */
function createClientForm() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss.getSheetByName(CUSTOMERS_TAB)) {
    throw new Error('No "' + CUSTOMERS_TAB + '" tab. Connect this sheet in the Simple CRM app first.');
  }

  const form = FormApp.create(FORM_TITLE)
    .setDescription(FORM_DESCRIPTION)
    .setConfirmationMessage('Thank you! Your information has been received.')
    .setCollectEmail(false)
    .setAllowResponseEdits(false)
    .setShowLinkToRespondAgain(false)
    .setProgressBar(false);

  QUESTIONS.forEach(function (q) {
    const item = q.paragraph ? form.addParagraphTextItem() : form.addTextItem();
    item.setTitle(q.title).setRequired(false);
    if (q.help) item.setHelpText(q.help);
    if (q.email) {
      item.setValidation(FormApp.createTextValidation()
        .setHelpText('Please enter a valid email address.').requireTextIsEmail().build());
    }
    if (q.zip) {
      item.setValidation(FormApp.createTextValidation()
        .setHelpText('Please enter a 5-digit ZIP code.').requireTextMatchesPattern('^\\d{5}(-\\d{4})?$').build());
    }
  });

  // Keep a raw copy of every answer in a "Form Responses" tab, as a backup.
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());

  // One trigger only, even if this is run again.
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'onClientFormSubmit') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('onClientFormSubmit').forSpreadsheet(ss).onFormSubmit().create();

  let shareLink = form.getPublishedUrl();
  try { shareLink = form.shortenFormUrl(shareLink); } catch (err) { /* keep the long link */ }
  Logger.log('Send this link to clients: ' + shareLink);
  Logger.log('Edit the form here: ' + form.getEditUrl());
  try {
    SpreadsheetApp.getUi().alert(
      'Client form created',
      'Send this link to clients:\n' + shareLink + '\n\nEdit the form (wording, logo, colors):\n' + form.getEditUrl(),
      SpreadsheetApp.getUi().ButtonSet.OK);
  } catch (err) { /* no sheet window open: the links are in the Execution log */ }
}

/** Runs automatically on every submission: adds the client to the Customers tab. */
function onClientFormSubmit(e) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(CUSTOMERS_TAB);
  const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0]
    .map(function (h) { return String(h).trim(); });
  const answers = (e && e.namedValues) || {};
  const answer = function (title) { return String((answers[title] || [''])[0] || '').trim(); };

  const rec = {};
  QUESTIONS.forEach(function (q) { rec[q.column] = answer(q.title); });
  if (!Object.keys(rec).some(function (k) { return rec[k]; })) return;  // blank submission

  if (/^[a-z]{2}$/i.test(rec['State'])) rec['State'] = rec['State'].toUpperCase();
  rec['Name'] = [rec['First Name'], rec['Middle Name'], rec['Last Name']].filter(String).join(' ');
  const today = Utilities.formatDate(new Date(), ss.getSpreadsheetTimeZone(), 'yyyy-MM-dd');
  rec['Date Added'] = today;
  rec['Notes'] = [rec['Notes'], 'Added from client form on ' + today + '.'].filter(String).join('\n');
  rec['Customer ID'] = '';  // the app assigns the next ID

  const row = header.map(function (h) { return rec[h] !== undefined ? rec[h] : ''; });
  const target = sheet.getRange(sheet.getLastRow() + 1, 1, 1, header.length);
  target.setNumberFormat('@');  // plain text, so ZIP codes and phone numbers keep leading zeros
  target.setValues([row]);
}
