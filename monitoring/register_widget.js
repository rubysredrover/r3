#!/usr/bin/env node
/**
 * Register MARS as a Bolo widget.
 *
 * Run once: node register_widget.js
 *
 * This registers the "mars" widget with Bolospot so Mom can
 * manage grants (permissions) for who can access Ruby's data.
 */

const BOLO_API_KEY = process.env.BOLO_API_KEY || 'bolo_live_0nrmjlWU_fFef1rg5OjS8neTPZhIoqgT';
const BASE_URL = 'https://api.bolospot.com';

async function registerMARS() {
  const widget = {
    slug: 'mars',
    name: 'MARS — Ruby\'s Red Rover',
    description:
      'Emotion awareness and companion system for the Innate MARS robot. ' +
      'Tracks mood, recognizes people, provides status updates, and sends alerts. ' +
      'Built for people with cerebral palsy and motor disabilities.',
    icon: '🤖',
    scopes: [
      'mood:read',          // read current mood
      'mood:history',       // view mood history / day summary
      'mood:notify',        // send mood change notifications
      'location:status',    // "where is Ruby?" status checks
      'location:beacon',    // activate Find My Ruby lights/sounds
      'person:register',    // register new people with MARS
      'person:list',        // view registered people
      'settings:manage',    // change scan intervals, thresholds
    ],
  };

  console.log('Registering MARS widget with Bolospot...\n');
  console.log('Widget:', JSON.stringify(widget, null, 2));
  console.log('');

  const response = await fetch(`${BASE_URL}/api/widgets/register`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${BOLO_API_KEY}`,
    },
    body: JSON.stringify(widget),
  });

  if (!response.ok) {
    const error = await response.text();
    console.error(`Registration failed (${response.status}):`, error);
    process.exit(1);
  }

  const result = await response.json();
  console.log('Widget registered successfully!\n');
  console.log('Result:', JSON.stringify(result, null, 2));
  console.log('\n--- Next steps ---');
  console.log('Mom can now grant access to MARS scopes:');
  console.log('  mood:read       — let someone check Ruby\'s mood');
  console.log('  mood:history    — let someone see mood over time');
  console.log('  mood:notify     — let MARS send mood alerts');
  console.log('  location:status — let someone ask "where\'s Ruby?"');
  console.log('  location:beacon — let someone trigger Find My Ruby');
  console.log('  person:register — let someone register new people');
  console.log('  person:list     — let someone view known people');
  console.log('  settings:manage — let someone change MARS settings');
}

registerMARS().catch(console.error);
