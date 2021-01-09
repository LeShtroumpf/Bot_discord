import random as rd
from ressource import dict_map, dict_defi


def game():

    game = []
    map = rd.randint(1, len(dict_map) - 1)
    challenge = rd.randint(1, len(dict_defi)-1)
    if map == 3:
        department = rd.randint(1, 95)
        game.append([map, challenge, department])
    else:
        pass
        game.append([map, challenge])
    print(f"game python: {game}")
    channel = 780779953288773702
    if ctx.channel.id != channel:
        print("mauvais channel")
        pass
    else:
        print(f"Bon channel", f"game = {game[0]}", f"map = {dict_map[game[0]]}")
        if game[0] == 3:
            print(f"Voici la carte sélectionné: {dict_map[game[0]]}.\n",
                  f"Voici le challenge sélectionné: {dict_defi[game[1]]}.\n",
                  f"Et enfin voici le département sélectionné: {game[2]}")
            await ctx.channel.send(f"Voici la carte sélectionné: {dict_map[game[0]]}.\n",
                                   f"Voici le challenge sélectionné: {dict_defi[game[1]]}.\n",
                                   f"Et enfin voici le département sélectionné: {game[2]}")
        else:
            print(f"Voici la carte sélectionné: {dict_map[0]}.\n",
                  f"Voici le challenge sélectionné: {dict_defi[game[1]]}.")
            await ctx.context.send(f"Voici la carte sélectionné: {dict_map[0]}.\n",
                                   f"Voici le challenge sélectionné: {dict_defi[game[1]]}.")

