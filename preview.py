"""Render a representative brief to preview.html for the visual check.

test_render_visual.py measures computed style in a real browser — contrast,
typeface count, horizontal overflow — and none of that is visible by reading
the HTML. It needs a page to measure, and nothing produced one, so the check
existed and never ran.

This builds a digest that exercises every section, so the measurement covers
the whole brief rather than whatever happened to be in the news.

    python3 preview.py && BRIEF_HTML=preview.html python3 test_render_visual.py
"""
import pathlib
import render

DIGEST = {'also_today': [{'body_text': 'Semiconductors led exports.',
                 'category': 'trade',
                 'headline': 'Customs reports a narrower September deficit',
                 'source': 'Korea Customs',
                 'url': 'https://example.org/6'},
                {'body_text': 'Testimony begins next week.',
                 'category': 'politics',
                 'headline': 'Assembly committee sets a budget hearing',
                 'source': 'Newsis',
                 'url': 'https://example.org/7'}],
 'bp_locations': [{'direction': 'up',
                   'last_source_date': '2026-09-05',
                   'name': 'Yongbyon Nuclear Complex',
                   'note': 'Thermal signatures consistent with a reprocessing '
                           'campaign.',
                   'status': 'elevated'},
                  {'last_source_date': '2026-09-07',
                   'name': 'Sohae Satellite Launching Station',
                   'note': 'Vehicle movement at the assembly building.',
                   'status': 'activity'}],
 'calendar_watch': [{'confirmed': True,
                     'date': '2026-09-12',
                     'day': 12,
                     'detail': 'First since the pact.',
                     'event': 'PIF leaders meet',
                     'headline': 'PIF leaders meet',
                     'month': 'Sep',
                     'why_it_matters': 'First since the pact.'}],
 'issue_no': 168,
 'key_stat': {'context': 'Largest single-year increase since 2017.',
              'label': 'Rise in the 2027 defence budget request',
              'number': '8.2%',
              'source': 'Ministry of Economy and Finance'},
 'market_indicators': {'brent': {'change_pct': -1.1, 'value': '72.40'},
                       'kospi': {'change_pct': 0.8, 'value': '2,714.30'},
                       'usd_krw': {'change_pct': -0.3, 'value': '1,338.20'}},
 'morning_memo': ['**Lee Jae-myung** approved a defence request up *more than 8 '
                  'percent*, the largest single-year rise since 2017.',
                  '**Kim Jong Un** has not appeared publicly in twelve days.',
                  'Seoul and Washington opened a fourth round of tariff talks with no '
                  'joint statement.'],
 'overnight_items': [{'body_text': 'No military display reported.',
                      'category': 'DPRK',
                      'headline': 'KCNA marks the founding anniversary without a '
                                  'parade',
                      'source': 'KCNA Watch',
                      'url': 'https://example.org/3'},
                     {'body_text': 'No joint statement issued.',
                      'category': 'Trade',
                      'headline': 'Fourth round of tariff talks opens',
                      'source': 'Korea Herald',
                      'url': 'https://example.org/4'},
                     {'body_text': 'First meeting since March.',
                      'category': 'Region',
                      'headline': 'Japan and China resume maritime consultations',
                      'source': 'Kyodo',
                      'url': 'https://example.org/5'}],
 'pdf_url': 'https://example.org/digest_2026-09-09.pdf',
 'public_sentiment': {'party_independent': {'value': '24%'},
                      'party_opposition': {'party': 'People Power Party',
                                           'value': '31%'},
                      'party_ruling': {'party': 'Democratic Party', 'value': '38%'},
                      'presidential_approval': {'last_updated': 'Sep 4, 2026',
                                                'source': 'Gallup Korea',
                                                'value': '40%'}},
 're_line': 'DPRK destroyer commissioned · Kang Kon enters East Sea · Lee in Paris',
 'top_stories': [{'body': '**Lee Jae-myung** approved a 2027 request rising *more than '
                          '8 percent*. The National Assembly takes it up next month.',
                  'category_tag': 'Security',
                  'headline': 'Cabinet clears record defence request',
                  'source': 'Yonhap',
                  'src_line': 'per Yonhap: "Cabinet approves record defence budget"',
                  'url': 'https://example.org/1'},
                 {'body': 'The board held for a third meeting, citing household debt. '
                          'Governor **Rhee Chang-yong** said the bar for a cut had '
                          'risen.',
                  'category_tag': 'Economy',
                  'headline': 'Bank of Korea holds at 2.50 percent',
                  'source': 'Reuters',
                  'src_line': 'per Reuters: "Bank of Korea holds"',
                  'url': 'https://example.org/2'}],
 'web_url': 'https://andysaulim.github.io/Daily-Korea-Digest/latest.html'}

if __name__ == "__main__":
    html = render.render(dict(DIGEST))
    pathlib.Path("preview.html").write_text(html, encoding="utf-8")
    print(f"preview.html written ({len(html):,} chars)")
