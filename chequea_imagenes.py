import os
from PIL import Image

#   Num   Pix       Color
#   0 -> 27,31 -> (125,125,125)
#   1 -> 32,28 -> (255,255,255)
#   2 -> 33,33 -> (78,78,78)
#   3 -> 29,29 -> (208,208,208)
#   4 -> 31,34 -> (78,78,78)
#   5 -> 26,32 -> (78,78,78)
#   6 -> 28,28 -> (184,184,184)
#   7 -> 26,23 -> (184,184,184)
#   8 -> 29,29 -> (78,78,78)
#   9 -> 33,29 -> (125,125,125)

def compara_color(t1, t2):
    return t1[0] == t2[0] and t1[1] == t2[1] and t1[2] == t2[2]

def parse_pin(pix):
    num_resultados = 0
    resultado = None
    if  compara_color(pix[27,31], (125,125,125)):
        resultado = 0
        num_resultados += 1
    if  compara_color(pix[32,28], (255,255,255)):
        resultado = 1
        num_resultados += 1
    if  compara_color(pix[33,33], (78,78,78)):
        resultado = 2
        num_resultados += 1
    if  compara_color(pix[29,29], (208,208,208)):
        resultado = 3
        num_resultados += 1
    if  compara_color(pix[31,34], (78,78,78)):
        resultado = 4
        num_resultados += 1
    if  compara_color(pix[26,32], (78,78,78)):
        resultado = 5
        num_resultados += 1
    if  compara_color(pix[28,28], (184,184,184)):
        resultado = 6
        num_resultados += 1
    if  compara_color(pix[26,23], (184,184,184)):
        resultado = 7
        num_resultados += 1
    if  compara_color(pix[29,29], (78,78,78)):
        resultado = 8
        num_resultados += 1
    if  compara_color(pix[33,29], (125,125,125)):
        resultado = 9
        num_resultados += 1

    if num_resultados != 1:
        raise Exception("Encontrado mas de un resultado!")

    return resultado
