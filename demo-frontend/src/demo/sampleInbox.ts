// A small made-up inbox for visitors without a benefit email to hand. Each one
// is sent to the real AI extractor, so the results show the same behaviour as
// a real email: an exact date, a date worked out from a duration, a vague
// expiry that goes to the review queue, and an ad that isn't a benefit at all.
// Dates are written relative to today so the samples never go stale.

export interface SampleEmail {
  id: string
  from: string
  subject: string
  /** YYYY-MM-DD */
  received: string
  /** What the panel says this sample shows. */
  note: string
  body: string
}

const DAY_MS = 86_400_000

function day(offset: number): Date {
  const d = new Date()
  return new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) + offset * DAY_MS)
}
const iso = (offset: number) => day(offset).toISOString().slice(0, 10)
const long = (offset: number) =>
  day(offset).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })

export function sampleInbox(): SampleEmail[] {
  return [
    {
      id: 'bakery',
      from: 'Bluebird Bakery <hello@bluebird-bakery.example>',
      subject: 'A little something for you',
      received: iso(-2),
      note: 'Voucher with an exact date and a code',
      body: `Hi Alex,

Thanks for being a Bluebird regular! Enjoy a free pastry of your choice with any coffee.

Show this code at the counter: BLUE-PASTRY
Valid until ${long(9)}. In store only, one per visit.

See you soon,
The Bluebird team`,
    },
    {
      id: 'gym',
      from: 'PeakFit Studios <members@peakfit.example>',
      subject: 'Your free month starts now',
      received: iso(-6),
      note: 'Free trial: the date is worked out from a duration',
      body: `Welcome to PeakFit, Alex!

Your free trial membership started on ${long(-6)} and lasts 30 days. Book unlimited classes in the app during your trial.

If you don't cancel before the trial ends, your membership continues at $49 a month.`,
    },
    {
      id: 'grocery',
      from: 'Maple Grocery Rewards <rewards@maplegrocery.example>',
      subject: 'Double points are back',
      received: iso(-1),
      note: 'Vague expiry: goes to the review queue',
      body: `Hello Maple Rewards member,

Double points are back! Earn 2x points on every shop, online or in store, while stocks last.

Your points post within 7 days of each purchase. Happy shopping!`,
    },
    {
      id: 'cinema',
      from: 'CineMax Theatres <offers@cinemax.example>',
      subject: 'Upgrade your next movie on us',
      received: iso(-3),
      note: 'Voucher with a day/month/year date',
      body: `Hi Alex,

As a CineMax Plus member, your next IMAX or 4DX ticket upgrade is on us.

Use promo code CMX-UPGRADE when booking. Offer valid till ${day(15).toLocaleDateString('en-GB', { timeZone: 'UTC' })}.
One upgrade per booking.`,
    },
    {
      id: 'card-ad',
      from: 'Horizon Bank <promotions@horizonbank.example>',
      subject: 'Earn 20,000 bonus miles with the Horizon Voyager Card',
      received: iso(-4),
      note: 'An ad for a new card: not a benefit, so it’s skipped',
      body: `Apply for the Horizon Voyager Card by ${long(20)} and earn 20,000 bonus miles when you spend $3,000 in your first 3 months.

Apply now at horizonbank.example/voyager. Terms and conditions apply.`,
    },
  ]
}

/** The text the AI reads: headers first, like an email read from an inbox. */
export const sampleText = (e: SampleEmail) =>
  `From: ${e.from}\nSubject: ${e.subject}\nDate: ${long(Math.round((Date.parse(e.received) - day(0).getTime()) / DAY_MS))}\n\n${e.body}`
