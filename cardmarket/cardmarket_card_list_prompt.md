I need a python script which scrapes through the cardmarket.com and gathers the data about the cards. 

First of all, i have locally the cardmarket_expansion_list.json file which contains all expansion names and ids. Structure is the following:

[
  {
    "expansion_id": 1651,
    "expansion_name": "2-Player Starter Deck Yuya & Declan"
  },


It is important because the script should query the following website where the idExpansion = expansion_id. The site parameter is important, because the script should iterate through all pages.

https://www.cardmarket.com/en/YuGiOh/Products/Search?searchMode=v1&idCategory=0&idExpansion=4225&onlyAvailable=on&idRarity=0&site=1

If no results found, the cardmarket reveals the following message in it's html code:

<div class="table table-striped"><div class="table-body"><p class="noResults text-center h3 text-muted py-5">Sorry, no matches for your query</p></div><div class="table-footer"></div></div>

It means, that the given page not exists, and the script should go on with the next expansion_id.

The script should update the cardmarket_expansion_list.json file with the total number of cards which have been found. For the given expansion if there is no parameter in the json file yet, it should create it as total_number_of_cards as it follows:

[
  {
    "expansion_id": 1651,
    "expansion_name": "2-Player Starter Deck Yuya & Declan",
    "total_number_of_cards": 42
  },


If no cards found at all, the script should create this row with the total quantity 0 furthermore it should create a separate json file cardmarket_empty_expansions.json and save the information in it. Furthermore on the console it should inform the user that how many empty expansions there are and how many cards have been saved. 

If the script searches the card data on the portal it will see the following html code:

<div class="table table-striped mb-3"><div class="table-header d-none d-md-flex"><div class="row g-0 flex-nowrap"><div class="d-none col">#</div><div class="col-icon"></div><div class="col-icon small"></div><div class="col"><div class="row g-0 h-100"><div class="col-10 col-md-8 px-2 flex-column align-items-start justify-content-center"><div>Name</div></div><div class="col-md-2 d-none d-lg-flex has-content-centered"><div>Number</div></div><div class="col-sm-2 d-none d-sm-flex has-content-centered"><div>Rarity</div></div></div></div><div class="col-availability px-2">Available</div><div class="col-price pe-sm-2">From</div></div></div><div class="table-body"><div id="productRow283144" class="row g-0"><div class="d-none col">1</div><div class="col-icon"><span data-bs-title="&lt;img src=&quot;https://product-images.s3.cardmarket.com/5/YS15/283144/283144.jpg&quot; alt=&quot;Mirror Force&quot;&gt;" data-bs-toggle="tooltip" data-bs-html="true" data-bs-placement="bottom" class="thumbnail-icon icon is-24x24 is-yugioh"><span class="fonticon-camera"></span></span></div><div class="col-icon small"><a href="/en/YuGiOh/Expansions/2Player-Starter-Deck-Yuya-Declan" data-bs-toggle="tooltip" data-bs-html="true" data-bs-placement="bottom" class="expansion-symbol is-yugioh is-text yugiohExpansionIcon" data-bs-original-title="2-Player Starter Deck Yuya &amp; Declan"><span>YS15</span></a></div><div class="col"><div class="row g-0"><div class="col-10 col-md-8 px-2 flex-column align-items-start justify-content-center"><div><a href="/en/YuGiOh/Products/Singles/2Player-Starter-Deck-Yuya-Declan/Mirror-Force">Mirror Force</a></div></div><div class="col-md-2 d-none d-lg-flex has-content-centered"><div>D16</div></div><div class="col-sm-2 d-none d-sm-flex has-content-centered"><div><span class="d-none d-md-flex"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16px" height="16px" data-bs-toggle="tooltip" data-bs-html="true" data-bs-placement="bottom" aria-label="Super Rare" data-bs-original-title="Super Rare"><path d="M8 1c3.9 0 7 3.1 7 7s-3.1 7-7 7-7-3.1-7-7 3.1-7 7-7Z" fill="#ccb473"></path><path d="M8 0C3.6 0 0 3.6 0 8s3.6 8 8 8 8-3.6 8-8-3.6-8-8-8Zm0 15c-3.9 0-7-3.1-7-7s3.1-7 7-7 7 3.1 7 7-3.1 7-7 7Z" fill="#fff"></path></svg></span></div></div></div></div><div class="col-availability px-2"><span class="d-none d-md-inline">509</span></div><div class="col-price pe-sm-2">0,03 €</div></div>


Based on these data the script should create a new file called cardmarket_card_list.json which contains the data from the above html code. The structure should be the following:

[
  {
    "expansion_id": 1651,
    "expansion_name": "2-Player Starter Deck Yuya & Declan",
    "expansion_code": "YS15",
    "card_id": 283144,
    "card_name": "Mirror Force",
    "card_number": "D16",
    "card_rarity": "Super Rare",
    "card_url": "https://www.cardmarket.com/en/YuGiOh/Products/Singles/2Player-Starter-Deck-Yuya-Declan/Mirror-Force"
  },

Just for information, the expansion_id and the card_id are the identification numbers on the cardmarket.com and not used by Konami. This info is important because of documentation purposes for later.



